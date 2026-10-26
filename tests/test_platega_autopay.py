import importlib
import io
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import orjson
import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fluent_compiler.bundle import FluentBundle
from fluentogram.translator import FluentTranslator
from httpx import AsyncClient, MockTransport, Response
from pydantic import SecretStr
from remnapy.exceptions import ConflictError
from remnapy.exceptions.general import ApiErrorResponse
from starlette.requests import Request

from src.application.dto import (
    PaymentGatewayDto,
    PlanDto,
    PlanDurationDto,
    PlanPriceDto,
    PlanSnapshotDto,
    PriceDetailsDto,
    SubscriptionDto,
    TransactionDto,
    UserDto,
)
from src.application.dto.payment_gateway import PlategaGatewaySettingsDto
from src.application.services import PricingService
from src.application.use_cases.gateways.commands.configuration import (
    UpdatePaymentGatewaySettings,
    UpdatePaymentGatewaySettingsDto,
)
from src.core.constants import CONTAINER_KEY, USER_KEY
from src.core.enums import Currency, PaymentGatewayType, PlanType, PurchaseType, TransactionStatus
from src.infrastructure.di.providers.retort import RetortProvider
from src.infrastructure.payment_gateways.platega import PlategaGateway
from src.infrastructure.services.platega_autopay import PlategaAutopayService
from src.infrastructure.services.remnawave import RemnawaveImpl
from src.infrastructure.services.remnawave_v3 import RemnawaveV3Impl
from src.telegram.routers.subscription import autopay as autopay_handlers
from src.telegram.routers.subscription.dialog import (
    autopay_confirm_window,
    autopay_window,
    payment_method,
)
from src.telegram.states import Subscription
from src.web.endpoints import payments


def _gateway() -> PlategaGateway:
    gateway = PlategaGateway.__new__(PlategaGateway)
    gateway.data = PaymentGatewayDto(
        type=PaymentGatewayType.PLATEGA,
        currency=Currency.RUB,
        is_active=True,
        settings=PlategaGatewaySettingsDto(
            merchant_id="merchant", api_key=SecretStr("secret"), autopay_enabled=True
        ),
    )
    gateway.settings = gateway.data.settings
    gateway.merchant_id = "merchant"
    gateway.api_key = "secret"
    gateway.recurring_webhook = None
    gateway.selected_payment_method = None
    return gateway


def _request(payload: dict, *, valid: bool = True) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [
                (b"x-merchantid", b"merchant"),
                (b"x-secret", b"secret" if valid else b"wrong"),
            ],
        },
        receive=AsyncMock(
            return_value={
                "type": "http.request",
                "body": orjson.dumps(payload),
                "more_body": False,
            }
        ),
    )


async def test_create_uses_subscription_method_not_normal_payment_endpoint():
    gateway = _gateway()
    requests = []
    subscription_id = uuid4()

    def respond(request):
        requests.append(request)
        return Response(
            200,
            json={
                "transactionId": str(subscription_id),
                "redirect": "https://pay.platega.io/subscription/1",
            },
        )

    async with AsyncClient(
        base_url="https://app.platega.io", transport=MockTransport(respond)
    ) as client:
        gateway._client = client
        result = await gateway.create_subscription(Decimal(450), "VPN", 90)
    assert result.id == subscription_id
    assert requests[0].url.path == "/transaction/process"
    assert json.loads(requests[0].content) == {
        "paymentMethod": 6,
        "paymentDetails": {"amount": 450, "currency": "RUB", "interval": 3, "intervalCount": 3},
        "description": "VPN",
    }


@pytest.mark.parametrize("days", [0, -1, 45, 400, 1460])
def test_rejects_durations_platega_cannot_represent(days):
    with pytest.raises(ValueError):
        PlategaGateway.subscription_interval(days)


async def test_subscription_events_are_authenticated_and_never_treated_as_a_payment():
    gateway = _gateway()
    subscription_id = str(uuid4())
    payload = {
        "Id": subscription_id,
        "SubscriptionId": subscription_id,
        "Status": "SUBSCRIPTION_ACTIVATED",
        "PaymentMethod": 6,
    }
    with pytest.raises(PermissionError):
        await gateway.handle_webhook(_request(payload, valid=False))
    assert gateway.recurring_webhook is None
    assert await gateway.handle_webhook(_request(payload)) is None
    assert gateway.recurring_webhook["subscriptionId"] == subscription_id
    # The factory caches gateways: the next ordinary callback must not reuse subscription data.
    payment_id = uuid4()
    result = await gateway.handle_webhook(
        _request(
            {
                "id": str(payment_id),
                "status": "CONFIRMED",
                "paymentMethod": 2,
            }
        )
    )
    assert result == (payment_id, TransactionStatus.COMPLETED)
    assert gateway.recurring_webhook is None


async def test_charge_pascal_case_is_preserved_for_durable_processing():
    gateway = _gateway()
    payload = {
        "Id": str(uuid4()),
        "SubscriptionId": str(uuid4()),
        "Status": "CONFIRMED",
        "Amount": 450,
        "Currency": "RUB",
        "NextChargeAt": "2026-11-26T00:00:00Z",
    }
    assert await gateway.handle_webhook(_request(payload)) is None
    assert gateway.recurring_webhook["amount"] == 450
    assert gateway.recurring_webhook["nextChargeAt"] == "2026-11-26T00:00:00Z"


def _service():
    service = PlategaAutopayService.__new__(PlategaAutopayService)
    service.retort = RetortProvider().get_retort()
    service.session = SimpleNamespace(commit=AsyncMock(), execute=AsyncMock())
    service.remnawave = SimpleNamespace(
        get_user_by_uuid=AsyncMock(),
        update_user_email=AsyncMock(),
        update_user_subscription=AsyncMock(),
        reset_traffic=AsyncMock(),
        create_user=AsyncMock(),
    )
    service.subscription_dao = SimpleNamespace(
        get_current=AsyncMock(return_value=None),
        get_by_id=AsyncMock(),
        update=AsyncMock(),
        create=AsyncMock(),
        update_status=AsyncMock(),
    )
    service.transaction_dao = SimpleNamespace(
        get_by_payment_id=AsyncMock(return_value=None), create=AsyncMock(), update=AsyncMock()
    )
    service.user_dao = SimpleNamespace(
        get_by_id=AsyncMock(return_value=UserDto(id=1, name="User")),
        set_trial_available=AsyncMock(),
        update=AsyncMock(),
    )
    service.notifier = SimpleNamespace(notify_user=AsyncMock())
    service.assign_referral_rewards = SimpleNamespace(system=AsyncMock())
    service.current = AsyncMock(return_value=None)
    return service


async def test_panel_email_takes_precedence_and_supplied_email_updates_only_billing():
    service = _service()
    user = UserDto(id=1, name="User", email="login@example.org", is_email_verified=True)
    subscription = SimpleNamespace(user_remna_id=uuid4(), panel_user_id=None)
    service.subscription_dao.get_current.return_value = subscription
    service.remnawave.get_user_by_uuid.return_value = SimpleNamespace(email="panel@example.org")
    assert await service.email(user) == "panel@example.org"
    service.remnawave.update_user_email.assert_not_awaited()
    assert await service.email(user, "billing@example.org") == "billing@example.org"
    service.remnawave.update_user_email.assert_awaited_once_with(
        subscription.user_remna_id, "billing@example.org"
    )
    assert user.email == "login@example.org"
    assert user.is_email_verified


async def test_missing_email_is_allowed_and_explicit_input_is_validated():
    service = _service()
    assert await service.email(UserDto(id=1, name="User")) is None
    with pytest.raises(ValueError):
        await service.email(UserDto(id=1, name="User"), "bad-email")


async def test_connecting_autopay_skips_email_screen_and_lookup():
    service = _service()
    service.gateway = AsyncMock()
    service.email = AsyncMock(side_effect=AssertionError("Email must not block confirmation"))
    plan = PlanDto(
        id=1,
        name="VPN",
        durations=[
            PlanDurationDto(
                days=30, prices=[PlanPriceDto(currency=Currency.RUB, price=Decimal(450))]
            )
        ],
    )
    manager = SimpleNamespace(dialog_data={}, switch_to=AsyncMock())
    await autopay_handlers._prepare(
        manager,
        UserDto(id=1, name="User"),
        plan,
        30,
        PurchaseType.NEW,
        service.retort,
        PricingService(),
        service,
    )
    manager.switch_to.assert_awaited_once_with(Subscription.AUTOPAY_CONFIRM)
    service.email.assert_not_awaited()
    assert "ap_email" not in manager.dialog_data
    assert autopay_window.find("autopay_email") is not None
    assert autopay_confirm_window.find("autopay_email") is None


@pytest.mark.parametrize("email_error", [None, TimeoutError("Panel unavailable")])
async def test_subscription_can_be_created_without_email(email_error):
    service = _service()
    service.redis = SimpleNamespace(lock=Mock(return_value=AsyncMock()))
    service.session.add = Mock()
    gateway = SimpleNamespace(
        subscription_interval=PlategaGateway.subscription_interval,
        create_subscription=AsyncMock(
            return_value=SimpleNamespace(id=uuid4(), url="https://pay.platega.io/subscription/new")
        ),
        settings=SimpleNamespace(autopay_display_name="Автоплатёж"),
    )
    service.gateway = AsyncMock(return_value=gateway)
    if email_error:
        service.email = AsyncMock(side_effect=email_error)
    plan = replace(PlanSnapshotDto.test(), duration=30)
    payment = await service.create(
        UserDto(id=1, name="User"), plan, PriceDetailsDto.test(), PurchaseType.NEW
    )
    assert payment.email is None
    gateway.create_subscription.assert_awaited_once()
    service.session.add.assert_called_once_with(payment)


async def test_optional_email_is_saved_without_autopay_or_panel_user():
    service = _service()
    user = UserDto(id=1, name="User", email="login@example.org", is_email_verified=True)
    await service.save_email(user, "billing@example.org")
    assert user.billing_email == "billing@example.org"
    assert user.email == "login@example.org"
    assert user.is_email_verified
    service.user_dao.update.assert_awaited_once_with(user)
    service.session.commit.assert_awaited_once()
    service.remnawave.update_user_email.assert_not_awaited()
    assert await service.email(user) == "billing@example.org"


async def test_changing_email_updates_existing_autopay_and_panel():
    service = _service()
    user = UserDto(id=1, name="User")
    payment = SimpleNamespace(email="old@example.org")
    panel_id = uuid4()
    service.current.return_value = payment
    service.subscription_dao.get_current.return_value = SimpleNamespace(
        user_remna_id=panel_id, panel_user_id=None
    )
    service.remnawave.get_user_by_uuid.return_value = SimpleNamespace(email="old@example.org")
    await service.save_email(user, "new@example.org")
    assert payment.email == user.billing_email == "new@example.org"
    service.remnawave.update_user_email.assert_awaited_once_with(panel_id, "new@example.org")


async def test_email_input_returns_to_settings_instead_of_payment_confirmation():
    service = SimpleNamespace(save_email=AsyncMock())
    user = UserDto(id=1, name="User")
    container = SimpleNamespace(
        get=AsyncMock(
            side_effect=lambda dependency, **kwargs: (
                service if dependency is PlategaAutopayService else SimpleNamespace()
            )
        )
    )
    manager = SimpleNamespace(
        middleware_data={USER_KEY: user, CONTAINER_KEY: container}, switch_to=AsyncMock()
    )
    await autopay_handlers.on_autopay_email_input(
        SimpleNamespace(text="billing@example.org"), None, manager
    )
    service.save_email.assert_awaited_once_with(user, "billing@example.org")
    manager.switch_to.assert_awaited_once_with(Subscription.AUTOPAY)


async def test_duplicate_charge_callbacks_use_the_same_durable_identity():
    service = _service()
    payload = {"subscriptionId": str(uuid4()), "id": str(uuid4()), "status": "CONFIRMED"}
    first = await service.receive(payload)
    second = await service.receive({**payload, "nextChargeAt": "2026-12-01T00:00:00Z"})
    assert first == second
    cancelled = await service.receive({**payload, "status": "CANCELED"})
    assert first != cancelled


async def test_activation_does_not_grant_access_and_uses_authoritative_status():
    service = _service()
    service.refresh = AsyncMock()
    service._fulfill = AsyncMock()
    event = SimpleNamespace(payload={"status": "SUBSCRIPTION_ACTIVATED"}, processed_at=None)
    payment = SimpleNamespace()
    await service._process(event, payment)
    service.refresh.assert_awaited_once_with(payment)
    service._fulfill.assert_not_awaited()
    service.transaction_dao.create.assert_not_awaited()
    assert event.processed_at is not None


async def test_completed_charge_is_not_fulfilled_twice():
    service = _service()
    service.refresh = AsyncMock()
    service._fulfill = AsyncMock()
    service.transaction_dao.get_by_payment_id.return_value = SimpleNamespace(
        user_id=1, status=TransactionStatus.COMPLETED
    )
    payment = SimpleNamespace(user_id=1, pricing=service.retort.dump(PriceDetailsDto.test()))
    event = SimpleNamespace(
        payload={
            "status": "CONFIRMED",
            "id": str(uuid4()),
            "amount": 2,
            "currency": "RUB",
        },
        processed_at=None,
    )
    await service._process(event, payment)
    service._fulfill.assert_not_awaited()
    service.transaction_dao.create.assert_not_awaited()


async def test_wrong_amount_never_grants_access():
    service = _service()
    service._fulfill = AsyncMock()
    payment = SimpleNamespace(pricing=service.retort.dump(PriceDetailsDto.test()))
    event = SimpleNamespace(payload={"status": "CONFIRMED", "amount": 1, "currency": "RUB"})
    with pytest.raises(ValueError, match="amount/currency"):
        await service._process(event, payment)
    service._fulfill.assert_not_awaited()


@pytest.mark.parametrize("email", ["billing@example.org", None])
async def test_lost_panel_response_reuses_saved_expiration_and_does_not_reset_twice(email):
    service = _service()
    plan = PlanSnapshotDto(
        id=1, name="VPN", type=PlanType.BOTH, traffic_limit=100, device_limit=3, duration=30
    )
    expiry = datetime(2030, 1, 1, tzinfo=UTC)
    current = SubscriptionDto(
        id=7,
        user_id=1,
        user_remna_id=uuid4(),
        traffic_limit=100,
        device_limit=3,
        traffic_limit_strategy=plan.traffic_limit_strategy,
        expire_at=expiry,
        url="https://example.org/sub",
        plan_snapshot=plan,
    )
    service.subscription_dao.get_current.return_value = current
    service.subscription_dao.get_by_id.return_value = current
    service.remnawave.update_user_subscription.side_effect = [
        TimeoutError("reply lost"),
        None,
        None,
    ]
    transaction = TransactionDto(
        payment_id=uuid4(),
        user_id=1,
        status=TransactionStatus.PENDING,
        purchase_type=PurchaseType.RENEW,
        gateway_type=PaymentGatewayType.PLATEGA,
        pricing=PriceDetailsDto.test(),
        currency=Currency.RUB,
        plan_snapshot=plan,
    )
    event = SimpleNamespace(target=None)
    payment = SimpleNamespace(user_id=1, email=email)
    with pytest.raises(TimeoutError):
        await service._fulfill(event, payment, transaction)
    # The entitlement target is JSON-safe and persisted before making the remote request.
    json.dumps(event.target)
    assert service.session.commit.await_count == 1
    await service._fulfill(event, payment, transaction)
    await service._fulfill(event, payment, transaction)
    expirations = [
        call.kwargs["subscription"].expire_at
        for call in service.remnawave.update_user_subscription.await_args_list
    ]
    assert expirations == [expiry + timedelta(days=30)] * 3
    assert current.expire_at == expiry + timedelta(days=30)
    service.remnawave.reset_traffic.assert_awaited_once()
    if email is None:
        service.remnawave.update_user_email.assert_not_awaited()


async def test_pending_agreement_can_be_reopened():
    service = _service()
    gateway = SimpleNamespace(
        get_subscription=AsyncMock(
            return_value={
                "status": "PendingAgreement",
                "nextChargeAt": None,
            }
        )
    )
    service.gateway = AsyncMock(return_value=gateway)
    payment = SimpleNamespace(id=uuid4(), status="Pending")
    assert (await service.refresh(payment)).status == "Pending"


async def test_email_updates_are_partial_for_both_panel_versions():
    sdk = SimpleNamespace(users=SimpleNamespace(update_user=AsyncMock()))
    v2 = RemnawaveImpl(sdk)
    user_id = uuid4()
    await v2.update_user_email(user_id, "payer@example.org")
    assert sdk.users.update_user.await_args.args[0].model_dump(
        mode="json", by_alias=True, exclude_unset=True
    ) == {"uuid": str(user_id), "email": "payer@example.org"}
    v3 = RemnawaveV3Impl(sdk, SimpleNamespace(update_user=AsyncMock()))
    await v3.update_user_email(17, "payer@example.org")
    assert v3.client.update_user.await_args.args[0].model_dump(
        mode="json", by_alias=True, exclude_unset=True
    ) == {"id": 17, "email": "payer@example.org"}


def test_autopay_translations_compile_and_boolean_labels_render():
    translator = FluentTranslator(
        locale="ru",
        translator=FluentBundle.from_string(
            locale="ru",
            text="\n".join(
                p.read_text("utf-8") for p in Path("assets/translations/ru").glob("*.ftl")
            ),
            use_isolating=False,
        ),
    )
    assert "включены" in translator.get("btn-gateway-autopay-toggle", enabled=True)
    assert "отключены" in translator.get("btn-gateway-autopay-toggle", enabled=False)
    assert "Включён" == translator.get("autopay-status-active")
    assert "Добавить" in translator.get("btn-autopay-email", has_email=False)
    assert "Изменить" in translator.get("btn-autopay-email", has_email=True)
    assert "необязательна" in translator.get("msg-autopay-email")


async def test_cancel_failure_keeps_local_autopay_enabled():
    service = _service()
    lock = AsyncMock()
    service.redis = SimpleNamespace(lock=Mock(return_value=lock))
    payment = SimpleNamespace(id=uuid4(), status="Active", next_charge_at=datetime.now(UTC))
    service.session.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: [payment]))
    service.gateway = AsyncMock(
        return_value=SimpleNamespace(
            cancel_subscription=AsyncMock(side_effect=TimeoutError("no confirmation"))
        )
    )
    with pytest.raises(TimeoutError):
        await service.cancel_for_user(1)
    assert payment.status == "Active"
    service.session.commit.assert_not_awaited()


def test_migration_has_a_single_head_and_builds_postgres_tables():
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0054_platega_recurring_payments"
    )
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        migration.upgrade()
        migration.downgrade()
    sql = output.getvalue()
    assert "CREATE TABLE recurring_payments" in sql
    assert "CREATE TABLE recurring_payment_events" in sql
    assert "CREATE UNIQUE INDEX uq_recurring_payments_open_user" in sql
    assert "WHERE status IN ('Pending', 'Active', 'PastDue')" in sql
    assert "DROP TABLE recurring_payments" in sql


def test_optional_email_migration_preserves_existing_addresses():
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0054_platega_recurring_payments"
    )
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        migration.upgrade()
    sql = output.getvalue()
    assert "ALTER TABLE users ADD COLUMN billing_email VARCHAR(255)" in sql
    assert "email VARCHAR(255)," in sql
    assert "email VARCHAR(255) NOT NULL" not in sql
    assert "UPDATE" not in sql


async def test_recurring_webhook_ack_requires_durable_event_and_queue(monkeypatch):
    gateway = _gateway()
    enqueue = AsyncMock()
    monkeypatch.setattr(payments.handle_platega_autopay_task, "kiq", enqueue)
    autopay = SimpleNamespace(receive=AsyncMock(return_value="event-id"))
    kwargs = {
        "gateway_type": "platega",
        "config": SimpleNamespace(),
        "event_publisher": SimpleNamespace(),
        "get_payment_gateway_instance": SimpleNamespace(
            for_webhook=AsyncMock(return_value=gateway)
        ),
        "transaction_dao": SimpleNamespace(),
        "uow": SimpleNamespace(),
        "autopay": autopay,
    }
    payload = {
        "Id": str(uuid4()),
        "SubscriptionId": str(uuid4()),
        "Status": "CONFIRMED",
        "Amount": 450,
        "Currency": "RUB",
    }
    response = await payments._process_payment_webhook(request=_request(payload), **kwargs)
    assert response.status_code == 200
    autopay.receive.assert_awaited_once()
    enqueue.assert_awaited_once_with("event-id")
    enqueue.reset_mock()
    autopay.receive.side_effect = RuntimeError("database unavailable")
    response = await payments._process_payment_webhook(request=_request(payload), **kwargs)
    assert response.status_code == 503
    enqueue.assert_not_awaited()


async def test_recurring_checkout_is_a_separate_full_width_row():
    row = next(
        row for row in payment_method.keyboard.buttons if row.find("autopay_checkout") is not None
    )
    manager = SimpleNamespace(is_preview=lambda: False)
    assert await row.render_keyboard({"autopay_method": None}, manager) == []
    keyboard = await row.render_keyboard(
        {"autopay_method": {"title": "Мой автоплатёж", "amount": 450}}, manager
    )
    assert len(keyboard) == len(keyboard[0]) == 1
    assert keyboard[0][0].text == "Мой автоплатёж | 450₽"


async def test_global_toggle_does_not_parse_false_as_true():
    gateway = _gateway().data
    uow = AsyncMock()
    dao = SimpleNamespace(get_by_id=AsyncMock(return_value=gateway), update=AsyncMock())
    command = UpdatePaymentGatewaySettings(uow, dao, RetortProvider().get_retort())
    await command.system(
        UpdatePaymentGatewaySettingsDto(gateway_id=1, field_name="autopay_enabled", value="false")
    )
    assert gateway.settings.autopay_enabled is False


async def test_same_tariff_different_period_preserves_already_paid_time():
    service = _service()
    plan = PlanSnapshotDto(
        id=1, name="VPN", type=PlanType.BOTH, traffic_limit=100, device_limit=3, duration=90
    )
    expiry = datetime(2030, 1, 1, tzinfo=UTC)
    current = SubscriptionDto(
        id=7,
        user_id=1,
        user_remna_id=uuid4(),
        traffic_limit=100,
        device_limit=3,
        traffic_limit_strategy=plan.traffic_limit_strategy,
        expire_at=expiry,
        url="https://example.org/sub",
        plan_snapshot=replace(plan, duration=30),
    )
    service.subscription_dao.get_current.return_value = current
    service.subscription_dao.get_by_id.return_value = current
    transaction = TransactionDto(
        payment_id=uuid4(),
        user_id=1,
        status=TransactionStatus.PENDING,
        purchase_type=PurchaseType.RENEW,
        gateway_type=PaymentGatewayType.PLATEGA,
        pricing=PriceDetailsDto.test(),
        currency=Currency.RUB,
        plan_snapshot=plan,
    )
    await service._fulfill(
        SimpleNamespace(target=None),
        SimpleNamespace(user_id=1, email="billing@example.org"),
        transaction,
    )
    assert current.expire_at == expiry + timedelta(days=90)
    service.subscription_dao.create.assert_not_awaited()


async def test_new_panel_user_is_recoverable_after_a_lost_create_response_v2():
    sdk = SimpleNamespace(
        users=SimpleNamespace(
            create_user=AsyncMock(
                side_effect=ConflictError(409, ApiErrorResponse(message="Already exists"))
            )
        )
    )
    service = RemnawaveImpl(sdk)
    user = UserDto(id=1, telegram_id=123, name="User")
    remote = SimpleNamespace(short_uuid="saved-marker", telegram_id=123, username=user.remna_name)
    service.get_user_by_short_uuid = AsyncMock(return_value=remote)
    assert await service.create_user(user, short_uuid="saved-marker") is remote
    service.get_user_by_short_uuid.assert_awaited_once_with("saved-marker")
    remote.telegram_id = 456
    with pytest.raises(ConflictError):
        await service.create_user(user, short_uuid="saved-marker")
