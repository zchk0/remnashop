import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fluent_compiler.bundle import FluentBundle
from fluentogram.translator import FluentTranslator
from httpx import AsyncClient, HTTPStatusError, MockTransport, ReadTimeout, Response

from src.application.common import Notifier, TranslatorRunner
from src.application.common.dao import TransactionDao
from src.application.dto import PlanSnapshotDto, PriceDetailsDto, TransactionDto, UserDto
from src.application.events import UserPurchaseEvent
from src.application.use_cases.gateways.commands.payment import ProcessPayment, ProcessPaymentDto
from src.application.use_cases.gateways.commands.recheck import RecheckPayment
from src.core.constants import CONTAINER_KEY, TARGET_USER_ID, USER_KEY
from src.core.enums import Currency, PaymentGatewayType, PurchaseType, Role, TransactionStatus
from src.core.exceptions import PermissionDeniedError, PurchaseError
from src.core.utils.time import datetime_now
from src.infrastructure.payment_gateways import PlategaGateway
from src.telegram.routers.dashboard.users.user.dialog import transaction as transaction_window
from src.telegram.routers.dashboard.users.user.getters import transaction_getter
from src.telegram.routers.dashboard.users.user.handlers import on_payment_recheck


class PaymentHarness:
    def __init__(self):
        self.actor = UserDto(id=1, telegram_id=1, name="Admin", role=Role.ADMIN)
        self.buyer = UserDto(id=2, telegram_id=2, name="Buyer")
        self.transaction = TransactionDto(
            payment_id=uuid4(),
            user_id=self.buyer.id,
            status=TransactionStatus.CANCELED,
            purchase_type=PurchaseType.NEW,
            gateway_type=PaymentGatewayType.PLATEGA,
            pricing=PriceDetailsDto.test(),
            currency=Currency.RUB,
            plan_snapshot=replace(PlanSnapshotDto.test(), duration=30),
            created_at=datetime_now(),
        )
        self.response = {
            "id": str(self.transaction.payment_id),
            "status": "CONFIRMED",
            "paymentDetails": {"amount": 2, "currency": "RUB"},
        }
        self.http_status = 200
        self.http_error = None
        self.requests = []
        self.dao = SimpleNamespace(
            get_by_payment_id=AsyncMock(side_effect=lambda _: replace(self.transaction)),
            transition_status=AsyncMock(side_effect=self.transition),
            update_status=AsyncMock(side_effect=self.update_status),
        )
        self.notifier = SimpleNamespace(
            notify_user=AsyncMock(), notify_admins=AsyncMock(), notify_system=AsyncMock()
        )
        self.process = ProcessPayment(
            uow=AsyncMock(),
            user_dao=SimpleNamespace(get_by_id=AsyncMock(return_value=self.buyer)),
            transaction_dao=self.dao,
            subscription_dao=SimpleNamespace(get_current=AsyncMock(return_value=None)),
            referral_dao=SimpleNamespace(),
            event_publisher=SimpleNamespace(publish=AsyncMock()),
            notifier=self.notifier,
            redirect=SimpleNamespace(to_success_payment=AsyncMock(), to_failed_payment=AsyncMock()),
            assign_referral_rewards=SimpleNamespace(system=AsyncMock()),
            purchase_subscription=SimpleNamespace(system=AsyncMock()),
            autopay=SimpleNamespace(cancel_for_user=AsyncMock()),
        )
        self.gateway = PlategaGateway.__new__(PlategaGateway)
        self.provider = SimpleNamespace(for_webhook=AsyncMock(return_value=self.gateway))
        self.recheck = RecheckPayment(self.dao, self.provider, self.process)

    async def transition(self, payment_id, status, allowed):
        # Model the DAO's atomic conditional UPDATE, shared by concurrent callbacks.
        await asyncio.sleep(0)
        if self.transaction.status not in allowed:
            return None
        self.transaction.status = status
        return replace(self.transaction)

    async def update_status(self, payment_id, status):
        self.transaction.status = status
        return replace(self.transaction)

    def respond(self, request):
        self.requests.append(request)
        if self.http_error:
            raise self.http_error
        return Response(self.http_status, json=self.response)


@pytest.fixture
async def payment():
    harness = PaymentHarness()
    async with AsyncClient(
        base_url="https://app.platega.io",
        headers={"X-MerchantId": "test-merchant", "X-Secret": "test-secret"},
        transport=MockTransport(harness.respond),
    ) as client:
        harness.gateway._client = client
        yield harness


@pytest.mark.parametrize(
    "status", [TransactionStatus.CANCELED, TransactionStatus.PENDING, TransactionStatus.FAILED]
)
async def test_confirmed_payment_runs_purchase_and_notifications(payment, status):
    payment.transaction.status = status
    result = await payment.recheck(payment.actor, payment.transaction.payment_id)

    assert result.processed
    assert payment.transaction.status == TransactionStatus.COMPLETED
    payment.process.purchase_subscription.system.assert_awaited_once()
    purchase = payment.process.purchase_subscription.system.await_args.args[0]
    assert purchase.transaction.payment_id == payment.transaction.payment_id
    payment.process.assign_referral_rewards.system.assert_awaited_once()
    payment.process.redirect.to_success_payment.assert_awaited_once_with(2, PurchaseType.NEW)
    event = payment.process.event_publisher.publish.await_args.args[0]
    assert isinstance(event, UserPurchaseEvent)
    assert event.payment_id == payment.transaction.payment_id
    request = payment.requests[0]
    assert request.method == "GET"
    assert request.url.path == f"/transaction/{payment.transaction.payment_id}"
    assert request.headers["X-MerchantId"] == "test-merchant"
    assert request.headers["X-Secret"] == "test-secret"


async def test_repeated_and_concurrent_rechecks_fulfill_only_once(payment):
    results = await asyncio.gather(
        *(payment.recheck(payment.actor, payment.transaction.payment_id) for _ in range(3))
    )
    assert sum(result.processed for result in results) == 1
    assert not (await payment.recheck(payment.actor, payment.transaction.payment_id)).processed
    payment.process.purchase_subscription.system.assert_awaited_once()
    payment.process.event_publisher.publish.assert_awaited_once()
    payment.process.assign_referral_rewards.system.assert_awaited_once()


async def test_recheck_racing_with_callback_fulfills_only_once(payment):
    payment.transaction.status = TransactionStatus.PENDING
    await asyncio.gather(
        payment.recheck(payment.actor, payment.transaction.payment_id),
        payment.process.system(
            ProcessPaymentDto(
                payment.transaction.payment_id,
                TransactionStatus.COMPLETED,
                PaymentGatewayType.PLATEGA,
            )
        ),
    )
    payment.process.purchase_subscription.system.assert_awaited_once()


@pytest.mark.parametrize("status", [TransactionStatus.COMPLETED, TransactionStatus.REFUNDED])
async def test_terminal_transactions_are_not_fulfilled_again(payment, status):
    payment.transaction.status = status
    result = await payment.recheck(payment.actor, payment.transaction.payment_id)
    assert result.provider_status == "CONFIRMED"
    assert not result.processed
    assert payment.transaction.status == status
    payment.process.purchase_subscription.system.assert_not_awaited()


@pytest.mark.parametrize("status", ["PENDING", "CANCELED", "CHARGEBACKED", "DISPUTED"])
async def test_unconfirmed_payment_does_not_change_transaction(payment, status):
    payment.response["status"] = status
    result = await payment.recheck(payment.actor, payment.transaction.payment_id)
    assert result.provider_status == status
    assert not result.processed
    assert payment.transaction.status == TransactionStatus.CANCELED
    payment.dao.transition_status.assert_not_awaited()
    payment.process.purchase_subscription.system.assert_not_awaited()


@pytest.mark.parametrize(
    "patch",
    [
        {"id": str(uuid4())},
        {"id": None},
        {"status": None},
        {"paymentDetails": None},
        {"paymentDetails": {"amount": 1, "currency": "RUB"}},
        {"paymentDetails": {"amount": 2, "currency": "USD"}},
        {"paymentDetails": {"amount": "NaN", "currency": "RUB"}},
        {"paymentDetails": {"amount": "invalid", "currency": "RUB"}},
        {"subscriptionId": str(uuid4())},
    ],
)
async def test_invalid_api_response_never_grants_subscription(payment, patch):
    payment.response.update(patch)
    with pytest.raises(ValueError):
        await payment.recheck(payment.actor, payment.transaction.payment_id)
    payment.dao.transition_status.assert_not_awaited()
    payment.process.purchase_subscription.system.assert_not_awaited()


@pytest.mark.parametrize("http_status", [401, 404, 500])
async def test_api_error_never_changes_local_status(payment, http_status):
    payment.http_status = http_status
    with pytest.raises(HTTPStatusError):
        await payment.recheck(payment.actor, payment.transaction.payment_id)
    assert payment.transaction.status == TransactionStatus.CANCELED
    payment.dao.transition_status.assert_not_awaited()


async def test_purchase_failure_is_reported_and_can_be_retried(payment):
    payment.process.purchase_subscription.system.side_effect = RuntimeError("Panel unavailable")
    with pytest.raises(PurchaseError):
        await payment.recheck(payment.actor, payment.transaction.payment_id)
    assert payment.transaction.status == TransactionStatus.FAILED
    payment.process.redirect.to_success_payment.assert_not_awaited()
    payment.process.purchase_subscription.system.side_effect = None
    assert (await payment.recheck(payment.actor, payment.transaction.payment_id)).processed


async def test_notification_failure_does_not_report_api_failure_or_repeat_purchase(payment):
    payment.process.event_publisher.publish.side_effect = ValueError("Notification error")
    with pytest.raises(PurchaseError):
        await payment.recheck(payment.actor, payment.transaction.payment_id)
    assert payment.transaction.status == TransactionStatus.COMPLETED
    assert not (await payment.recheck(payment.actor, payment.transaction.payment_id)).processed
    payment.process.purchase_subscription.system.assert_awaited_once()


@pytest.mark.parametrize("role", [Role.USER, Role.PREVIEW])
async def test_server_checks_permissions_even_for_stale_button(payment, role):
    payment.actor.role = role
    with pytest.raises(PermissionDeniedError):
        await payment.recheck(payment.actor, payment.transaction.payment_id)
    payment.dao.get_by_payment_id.assert_not_awaited()
    assert not payment.requests


@pytest.mark.parametrize(
    "patch",
    [
        {"is_test": True},
        {"payment_method": "6"},
        {"gateway_type": PaymentGatewayType.TELEGRAM_STARS},
    ],
)
async def test_unsupported_transactions_cannot_be_recovered(payment, patch):
    payment.transaction = replace(payment.transaction, **patch)
    with pytest.raises(ValueError):
        await payment.recheck(payment.actor, payment.transaction.payment_id)
    assert not payment.requests


async def test_callback_does_not_implicitly_enable_manual_recovery(payment):
    assert not await payment.process.system(
        ProcessPaymentDto(
            payment.transaction.payment_id,
            TransactionStatus.COMPLETED,
            PaymentGatewayType.PLATEGA,
        )
    )
    assert payment.transaction.status == TransactionStatus.CANCELED
    payment.process.purchase_subscription.system.assert_not_awaited()


def translator():
    return FluentTranslator(
        locale="ru",
        translator=FluentBundle.from_string(
            locale="ru",
            text="\n".join(
                Path(f"assets/translations/ru/{name}.ftl").read_text("utf-8")
                for name in ("buttons", "notifications")
            ),
            use_isolating=False,
        ),
    )


@pytest.mark.parametrize("role", [Role.OWNER, Role.DEV, Role.ADMIN, Role.PREVIEW, Role.USER])
@pytest.mark.parametrize("origin", ["user", "all_transactions"])
async def test_card_renders_recheck_button_only_for_authorized_admins(payment, role, origin):
    payment.actor.role = role
    i18n = translator()
    manager = SimpleNamespace(
        dialog_data={
            TARGET_USER_ID: payment.buyer.id,
            "selected_transaction": payment.transaction.payment_id,
            "transaction_origin": origin,
        },
        middleware_data={
            USER_KEY: payment.actor,
            CONTAINER_KEY: SimpleNamespace(get=AsyncMock(return_value=i18n)),
        },
        is_preview=lambda: False,
    )
    data = await transaction_getter.__dishka_orig_func__(
        manager, payment.dao, SimpleNamespace(get_by_id=AsyncMock(return_value=payment.buyer)), i18n
    )
    button = transaction_window.find("payment_recheck")
    keyboard = await button.render_keyboard(data, manager)
    assert bool(keyboard) == (role in {Role.OWNER, Role.DEV, Role.ADMIN})
    if keyboard:
        assert keyboard[0][0].text == "🔄 Перепроверить оплату"


@pytest.mark.parametrize("unavailable", [False, True])
async def test_admin_gets_result_or_api_error_without_leaving_transaction_card(
    payment, unavailable
):
    if unavailable:
        payment.http_error = ReadTimeout("Platega unavailable")
    i18n = translator()
    callback = SimpleNamespace(answer=AsyncMock())
    dependencies = {
        RecheckPayment: payment.recheck,
        TransactionDao: payment.dao,
        Notifier: payment.notifier,
        TranslatorRunner: i18n,
    }
    container = SimpleNamespace(
        get=AsyncMock(side_effect=lambda dependency, **kwargs: dependencies[dependency])
    )
    manager = SimpleNamespace(
        dialog_data={"selected_transaction": str(payment.transaction.payment_id)},
        middleware_data={USER_KEY: payment.actor, CONTAINER_KEY: container},
    )
    await on_payment_recheck(callback, None, manager)
    callback.answer.assert_awaited_once_with("Проверяю статус оплаты…")
    notification = payment.notifier.notify_user.await_args.kwargs
    if unavailable:
        assert notification["i18n_key"] == "ntf-user.payment-recheck-error"
        payment.process.purchase_subscription.system.assert_not_awaited()
    else:
        payload = notification["payload"]
        assert payload.i18n_key == "ntf-user.payment-recheck-success"
        assert "подписка начислена" in i18n.get(payload.i18n_key, **payload.i18n_kwargs)
