import asyncio
import hashlib
import hmac
import importlib
import io
import json
import time
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import orjson
import pytest
from aiogram_dialog.utils import add_intent_id
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fakeredis.aioredis import FakeRedis
from fastapi import HTTPException
from fluent_compiler.bundle import FluentBundle
from fluentogram.translator import FluentTranslator
from httpx import AsyncClient, HTTPStatusError, MockTransport, ReadTimeout, Response
from pydantic import SecretStr
from starlette.requests import Request

from src.application.dto import (
    PaymentGatewayDto,
    PlanDto,
    PlanSnapshotDto,
    PriceDetailsDto,
    TransactionDto,
)
from src.application.dto.payment_gateway import RivaraGatewaySettingsDto
from src.application.dto.plan import PlanDurationDto, PlanPriceDto
from src.application.dto.user import TelegramUserDto, UserDto
from src.application.use_cases.gateways.commands.payment import (
    CreateDefaultPaymentGateway,
    CreatePayment,
    CreatePaymentDto,
    CreateTestPayment,
    ProcessPayment,
    ProcessPaymentDto,
)
from src.application.use_cases.gateways.commands.recheck import RecheckPayment
from src.application.use_cases.gateways.commands.rivara_methods import (
    UpdateRivaraPaymentMethod,
    UpdateRivaraPaymentMethodDto,
)
from src.application.use_cases.gateways.queries.providers import GetPaymentGatewayInstance
from src.core.constants import CONTAINER_KEY, PAYMENT_PREFIX, USER_KEY
from src.core.enums import Currency, PaymentGatewayType, PurchaseType, Role, TransactionStatus
from src.core.exceptions import PermissionDeniedError
from src.infrastructure.database.models import PaymentGateway
from src.infrastructure.di.providers.payment_gateways import PaymentGatewaysProvider
from src.infrastructure.di.providers.retort import RetortProvider
from src.infrastructure.payment_gateways import RivaraGateway
from src.infrastructure.services.cryptography import CryptographerImpl
from src.telegram.routers.dashboard.remnashop.gateways.dialog import rivara_methods
from src.telegram.routers.dashboard.remnashop.gateways.rivara_methods import rivara_methods_getter
from src.telegram.routers.subscription.dialog import payment_method as checkout_window
from src.telegram.routers.subscription.getters import (
    _get_payment_options,
    confirm_getter,
    payment_method_getter,
)
from src.telegram.routers.subscription.handlers import on_payment_method_select
from src.web.endpoints import payments
from src.web.endpoints.public import subscription as web_subscription
from src.web.schemas.subscription import PurchaseRequest


def settings():
    return RivaraGatewaySettingsDto(
        api_key=SecretStr("live_test_key"), webhook_secret=SecretStr("wh_test")
    )


def money(amount="200.10"):
    return PriceDetailsDto(
        original_amount=Decimal(amount), final_amount=Decimal(amount), discount_percent=0
    )


def transaction(**changes):
    return TransactionDto(
        payment_id=changes.pop("payment_id", uuid4()),
        provider_payment_id="pi_01M4PPHS2W9AFAFY7XQ7F1QJDA",
        user_id=1,
        status=changes.pop("status", TransactionStatus.PENDING),
        purchase_type=PurchaseType.NEW,
        gateway_type=PaymentGatewayType.RIVARAPAY,
        pricing=money(),
        currency=Currency.RUB,
        plan_snapshot=PlanSnapshotDto.test(),
        **changes,
    )


def payload(tx, **changes):
    return {
        "event_type": "payment.paid",
        "status": "paid",
        "amount": "200.10",
        "total": "210.10",
        "currency": "RUB",
        "test": False,
        "payment_id": tx.provider_payment_id,
        "order_id": str(tx.payment_id),
        **changes,
    }


def request(data, *, timestamp=None, signature=None, event_id="evt_1", raw_body=None):
    body = raw_body if raw_body is not None else orjson.dumps(data)
    timestamp = str(int(time.time())) if timestamp is None else timestamp
    signature = (
        signature
        if signature is not None
        else hmac.new(b"wh_test", timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    )
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [
                (b"x-signature", signature.encode()),
                (b"x-timestamp", timestamp.encode()),
                (b"x-event-id", event_id.encode()),
                (b"x-event-type", b"payment.created"),
            ],
        },
        receive=AsyncMock(return_value={"type": "http.request", "body": body, "more_body": False}),
    )


@pytest.fixture
async def gateway():
    dto = PaymentGatewayDto(
        id=1,
        type=PaymentGatewayType.RIVARAPAY,
        currency=Currency.RUB,
        is_active=True,
        settings=settings(),
    )
    bot = SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username="test_bot")))
    instance = RivaraGateway(dto, bot, SimpleNamespace())
    headers = instance._client.headers
    await instance._client.aclose()
    api = SimpleNamespace(requests=[], response=None, status=200, errors=[])

    def respond(req):
        api.requests.append(req)
        if api.errors:
            error = api.errors.pop(0)
            if isinstance(error, int):
                return Response(error, json={"error": {"code": "PROVIDER_ERROR"}})
            raise error
        if api.response is not None:
            return Response(api.status, json=api.response)
        data = json.loads(req.content)
        return Response(
            200,
            json={
                "id": "pi_" + data["merchantOrderId"].replace("-", ""),
                "merchantOrderId": data["merchantOrderId"],
                "livemode": not instance.is_test_mode,
                "status": "CREATED",
                "amount": {"amount": data["amount"], "currency": "RUB"},
                "checkoutUrl": "https://pay.rivarapay.io/checkout/test",
            },
        )

    async with AsyncClient(
        base_url=instance.API_BASE, headers=headers, transport=MockTransport(respond)
    ) as client:
        instance._client = client
        yield instance, api


def enable(instance, *ids):
    instance.settings.methods = [
        replace(method, enabled=method.id in ids) for method in instance.settings.payment_methods
    ]


@pytest.mark.parametrize("method_id", ["ALL", "SBP", "CARD_RU", "CARD_INTERNATIONAL", "CRYPTO"])
async def test_creation_uses_exact_method_minor_units_idempotency_and_customer(gateway, method_id):
    instance, api = gateway
    enable(instance, method_id)
    result = await instance.handle_create_payment(
        Decimal("200.10"),
        "Тариф",
        payment_method=method_id,
        customer_email="123@telegram.org",
    )
    req = api.requests[0]
    data = json.loads(req.content)
    assert req.url == "https://api.rivarapay.io/api/v1/payment-intents"
    assert req.headers["X-API-Key"] == "live_test_key"
    assert UUID(req.headers["Idempotency-Key"]) == result.id
    assert data["merchantOrderId"] == str(result.id)
    assert data["amount"] == "20010" and data["currency"] == "RUB"
    assert data["customerEmail"] == "123@telegram.org"
    assert data["returnUrl"] == "https://t.me/test_bot"
    if method_id == "ALL":
        assert "allowedMethods" not in data
    else:
        assert data["allowedMethods"] == [method_id]
    assert result.provider_payment_id.startswith("pi_")
    assert result.url == "https://pay.rivarapay.io/checkout/test"


@pytest.mark.parametrize("error", [503, 429, ReadTimeout("timeout")])
async def test_transient_creation_retry_keeps_the_same_order_and_request(gateway, error):
    instance, api = gateway
    api.errors = [error]
    await instance.handle_create_payment(
        Decimal("200.10"), "Тариф", customer_email="1@telegram.org"
    )
    first, second = api.requests
    assert first.content == second.content
    assert first.headers["Idempotency-Key"] == second.headers["Idempotency-Key"]


async def test_validation_error_does_not_retry(gateway):
    instance, api = gateway
    api.response, api.status = {"error": {"code": "PAYMENT_METHOD_UNAVAILABLE"}}, 422
    with pytest.raises(HTTPStatusError):
        await instance.handle_create_payment(
            Decimal("200"), "Тариф", customer_email="1@telegram.org"
        )
    assert len(api.requests) == 1


@pytest.mark.parametrize(
    "patch",
    [
        {"id": "invalid"},
        {"checkoutUrl": "javascript:alert(1)"},
        {"checkoutUrl": "https:///missing-host"},
        {"livemode": False},
        {"merchantOrderId": str(uuid4())},
        {"amount": {"amount": "200.10", "currency": "RUB"}},
        {"amount": {"amount": "20010", "currency": "USD"}},
    ],
)
async def test_invalid_creation_response_cannot_be_saved_as_checkout(gateway, patch):
    instance, api = gateway

    def respond(req):
        data = json.loads(req.content)
        return Response(
            200,
            json={
                "id": "pi_test",
                "merchantOrderId": data["merchantOrderId"],
                "livemode": True,
                "amount": {"amount": "20010", "currency": "RUB"},
                "checkoutUrl": "https://pay.rivarapay.io/test",
                **patch,
            },
        )

    instance._client._transport = MockTransport(respond)
    with pytest.raises(ValueError):
        await instance.handle_create_payment(
            Decimal("200.10"), "Тариф", customer_email="1@telegram.org"
        )


@pytest.mark.parametrize("amount", ["0", "-1", "1.001", "NaN", "Infinity"])
async def test_invalid_amount_does_not_call_api(gateway, amount):
    instance, api = gateway
    with pytest.raises(ValueError):
        await instance.handle_create_payment(
            Decimal(amount), "Тариф", customer_email="1@telegram.org"
        )
    assert not api.requests


async def test_disabled_unknown_or_ambiguous_method_does_not_call_api(gateway):
    instance, api = gateway
    enable(instance, "SBP", "CARD_RU")
    for method_id in (None, "ALL", "CRYPTO", "UNKNOWN"):
        with pytest.raises(ValueError):
            await instance.handle_create_payment(
                Decimal("200"), "Тариф", payment_method=method_id, customer_email="1@telegram.org"
            )
    assert not api.requests


async def test_admin_modes_names_and_permissions(gateway):
    instance, _ = gateway
    dao = SimpleNamespace(get_by_id=AsyncMock(return_value=instance.data), update=AsyncMock())
    edit = UpdateRivaraPaymentMethod(AsyncMock(), dao)
    assert [method.id for method in instance.settings.enabled_methods] == ["ALL"]
    for method_id in ("SBP", "CARD_RU", "CARD_INTERNATIONAL", "CRYPTO"):
        await edit.system(UpdateRivaraPaymentMethodDto(1, method_id, "toggle"))
    assert {method.id for method in instance.settings.enabled_methods} == {
        "SBP",
        "CARD_RU",
        "CARD_INTERNATIONAL",
        "CRYPTO",
    }
    await edit.system(UpdateRivaraPaymentMethodDto(1, "SBP", "rename", "  Мои банки  "))
    assert instance.settings.get_payment_method("SBP").title == "Мои банки"
    await edit.system(UpdateRivaraPaymentMethodDto(1, "ALL", "toggle"))
    assert [method.id for method in instance.settings.enabled_methods] == ["ALL"]
    await edit.system(UpdateRivaraPaymentMethodDto(1, "SBP", "toggle"))
    assert instance.settings.get_payment_method().title == "Мои банки"
    await edit.system(UpdateRivaraPaymentMethodDto(1, "SBP", "reset_name"))
    assert instance.settings.get_payment_method().title == "СБП"
    with pytest.raises(PermissionDeniedError):
        await edit(UserDto(name="Buyer"), UpdateRivaraPaymentMethodDto(1, "SBP", "toggle"))
    with pytest.raises(ValueError):
        await edit.system(UpdateRivaraPaymentMethodDto(1, "SBP", "rename", " "))
    # A partial saved list must not silently re-enable general checkout.
    instance.settings.methods = [instance.settings.get_payment_method("SBP")]
    assert [method.id for method in instance.settings.enabled_methods] == ["SBP"]


def create_service(instance, transactions, cls=CreatePayment):
    return cls(
        AsyncMock(),
        None,
        transactions,
        SimpleNamespace(system=AsyncMock(return_value=instance)),
        SimpleNamespace(
            get_translator_by_locale=lambda _: SimpleNamespace(get=lambda *a, **kw: "Тариф")
        ),
    )


async def test_checkout_concurrency_persists_external_ids_and_selected_titles(gateway):
    instance, api = gateway
    enable(instance, "SBP", "CRYPTO")
    transactions = SimpleNamespace(create=AsyncMock())
    create = create_service(instance, transactions)
    user = UserDto(id=1, telegram_id=123, name="Buyer")
    await asyncio.gather(
        *[
            create(
                user,
                CreatePaymentDto(
                    plan_snapshot=PlanSnapshotDto.test(),
                    pricing=money(),
                    purchase_type=PurchaseType.NEW,
                    gateway_type=PaymentGatewayType.RIVARAPAY,
                    payment_method=method_id,
                ),
            )
            for method_id in ("SBP", "CRYPTO")
        ]
    )
    saved = [call.args[0] for call in transactions.create.await_args_list]
    assert {(tx.payment_method, tx.gateway_display_name) for tx in saved} == {
        ("SBP", "СБП"),
        ("CRYPTO", "Криптовалюта"),
    }
    assert (
        len({tx.payment_id for tx in saved}) == len({tx.provider_payment_id for tx in saved}) == 2
    )
    assert all(
        json.loads(req.content)["customerEmail"] == "123@telegram.org" for req in api.requests
    )


async def test_test_key_cannot_create_real_purchase_but_can_create_admin_test(gateway):
    instance, api = gateway
    instance.is_test_mode = True
    transactions = SimpleNamespace(create=AsyncMock())
    user = UserDto(id=1, telegram_id=123, name="Owner", role=Role.OWNER)
    with pytest.raises(ValueError):
        await create_service(instance, transactions)(
            user,
            CreatePaymentDto(
                plan_snapshot=PlanSnapshotDto.test(),
                pricing=money(),
                purchase_type=PurchaseType.NEW,
                gateway_type=PaymentGatewayType.RIVARAPAY,
            ),
        )
    assert not api.requests
    await create_service(instance, transactions, CreateTestPayment)(
        user, PaymentGatewayType.RIVARAPAY
    )
    tx = transactions.create.await_args.args[0]
    assert tx.is_test and tx.provider_payment_id
    assert json.loads(api.requests[0].content)["customerEmail"] == "123@telegram.org"


def webhook_dependencies(instance, tx, redis):
    return {
        "gateway_type": "rivarapay",
        "config": SimpleNamespace(build=SimpleNamespace(data={})),
        "event_publisher": SimpleNamespace(publish=AsyncMock()),
        "get_payment_gateway_instance": SimpleNamespace(
            for_webhook=AsyncMock(return_value=instance)
        ),
        "transaction_dao": SimpleNamespace(get_by_payment_id=AsyncMock(return_value=tx)),
        "uow": AsyncMock(),
        "autopay": None,
        "redis": redis,
    }


async def test_signed_paid_callbacks_are_validated_and_deduplicated(gateway, monkeypatch):
    instance, _ = gateway
    tx = transaction()
    enqueue = AsyncMock()
    monkeypatch.setattr(payments.handle_payment_transaction_task, "kiq", enqueue)
    async with FakeRedis() as redis:
        deps = webhook_dependencies(instance, tx, redis)
        first, duplicate = await asyncio.gather(
            *[
                payments._process_payment_webhook(request=request(payload(tx)), **deps)
                for _ in range(2)
            ]
        )
        assert first.status_code in {200, 503} and duplicate.status_code in {200, 503}
        retry = await payments._process_payment_webhook(request=request(payload(tx)), **deps)
        assert retry.status_code == 200
        enqueue.assert_awaited_once_with(
            tx.payment_id, TransactionStatus.COMPLETED, PaymentGatewayType.RIVARAPAY
        )


@pytest.mark.parametrize(
    "patch",
    [
        {"amount": "199.99"},
        {"amount": "210.10"},
        {"amount": "20010"},
        {"currency": "USD"},
        {"order_id": "bad-id"},
        {"payment_id": "pi_other"},
        {"test": True},
        {"test": "false"},
        {"test": None},
        {"status": "SUCCEEDED"},
    ],
)
async def test_invalid_webhook_never_enqueues_purchase(gateway, monkeypatch, patch):
    instance, _ = gateway
    tx = transaction()
    enqueue = AsyncMock()
    monkeypatch.setattr(payments.handle_payment_transaction_task, "kiq", enqueue)
    async with FakeRedis() as redis:
        response = await payments._process_payment_webhook(
            request=request(payload(tx, **patch)), **webhook_dependencies(instance, tx, redis)
        )
    assert response.status_code == 400
    enqueue.assert_not_awaited()


@pytest.mark.parametrize(
    "options",
    [
        {"timestamp": "0"},
        {"timestamp": "NaN"},
        {"timestamp": str(int(time.time()) + 600)},
        {"signature": "bad"},
        {"signature": "a" * 64},
        {"event_id": ""},
    ],
)
async def test_invalid_authentication_never_enqueues(gateway, monkeypatch, options):
    instance, _ = gateway
    tx = transaction()
    enqueue = AsyncMock()
    monkeypatch.setattr(payments.handle_payment_transaction_task, "kiq", enqueue)
    async with FakeRedis() as redis:
        response = await payments._process_payment_webhook(
            request=request(payload(tx), **options), **webhook_dependencies(instance, tx, redis)
        )
    assert response.status_code == 400
    enqueue.assert_not_awaited()


async def test_raw_bytes_are_signed_and_unrelated_events_are_ignored(gateway):
    instance, _ = gateway
    tx = transaction()
    body = json.dumps(payload(tx), indent=2, ensure_ascii=False).encode()
    assert await instance.handle_webhook(request(None, raw_body=body)) == (
        tx.payment_id,
        TransactionStatus.COMPLETED,
    )
    for event in (
        "payment.created",
        "payment.refunded",
        "conversion.succeeded",
        "refund.succeeded",
    ):
        assert await instance.handle_webhook(request({"event_type": event})) is None


async def test_queue_outage_and_unsaved_order_request_retry(gateway, monkeypatch):
    instance, _ = gateway
    tx = transaction()
    enqueue = AsyncMock(side_effect=RuntimeError("queue unavailable"))
    monkeypatch.setattr(payments.handle_payment_transaction_task, "kiq", enqueue)
    async with FakeRedis() as redis:
        deps = webhook_dependencies(instance, tx, redis)
        assert (
            await payments._process_payment_webhook(request=request(payload(tx)), **deps)
        ).status_code == 503
        enqueue.side_effect = None
        assert (
            await payments._process_payment_webhook(request=request(payload(tx)), **deps)
        ).status_code == 200
        assert enqueue.await_count == 2
        deps["transaction_dao"].get_by_payment_id.return_value = None
        assert (
            await payments._process_payment_webhook(
                request=request(payload(tx), event_id="evt_2"), **deps
            )
        ).status_code == 503


async def test_methods_off_and_gateway_inactive_still_accept_existing_payment(gateway):
    instance, _ = gateway
    instance.data.is_active = False
    enable(instance)
    provider = GetPaymentGatewayInstance(
        AsyncMock(),
        SimpleNamespace(get_by_type=AsyncMock(return_value=instance.data)),
        lambda _: instance,
    )
    existing = await provider.for_webhook(PaymentGatewayType.RIVARAPAY)
    tx = transaction()
    assert await existing.handle_webhook(request(payload(tx))) == (
        tx.payment_id,
        TransactionStatus.COMPLETED,
    )


async def test_late_paid_event_after_local_timeout_fulfils_only_once(gateway):
    tx = transaction(status=TransactionStatus.CANCELED)

    async def transition(payment_id, status, allowed):
        if tx.status not in allowed:
            return None
        tx.status = status
        return tx

    process = ProcessPayment.__new__(ProcessPayment)
    process.uow = AsyncMock()
    process.transaction_dao = SimpleNamespace(
        get_by_payment_id=AsyncMock(return_value=tx),
        transition_status=AsyncMock(side_effect=transition),
    )
    process.user_dao = SimpleNamespace(
        get_by_id=AsyncMock(return_value=UserDto(id=1, name="Buyer"))
    )
    process._handle_success = AsyncMock()
    command = ProcessPaymentDto(
        tx.payment_id, TransactionStatus.COMPLETED, PaymentGatewayType.RIVARAPAY
    )
    assert await process.system(command)
    assert not await process.system(command)
    process._handle_success.assert_awaited_once()


@pytest.mark.parametrize(
    "patch",
    [
        None,
        {"livemode": False},
        {"id": "pi_other"},
        {"merchantOrderId": str(uuid4())},
        {"amount": {"amount": "21010", "currency": "RUB"}},
    ],
)
async def test_recheck_uses_external_id_and_validates_rest_minor_units(gateway, patch):
    instance, api = gateway
    tx = transaction()
    api.response = {
        "id": tx.provider_payment_id,
        "merchantOrderId": str(tx.payment_id),
        "livemode": True,
        "status": "SUCCEEDED",
        "amount": {"amount": "20010", "currency": "RUB"},
        **(patch or {}),
    }
    process = SimpleNamespace(system=AsyncMock(return_value=True))
    recheck = RecheckPayment(
        SimpleNamespace(get_by_payment_id=AsyncMock(return_value=tx)),
        SimpleNamespace(for_webhook=AsyncMock(return_value=instance)),
        process,
    )
    if patch:
        with pytest.raises(ValueError):
            await recheck.system(tx.payment_id)
        process.system.assert_not_awaited()
    else:
        result = await recheck.system(tx.payment_id)
        assert result.is_paid and result.processed
        assert api.requests[0].url.path == f"/api/v1/payment-intents/{tx.provider_payment_id}"


async def test_settings_encrypted_roundtrip_and_default_startup(gateway):
    instance, _ = gateway
    enable(instance, "SBP", "CRYPTO")
    provider = RetortProvider()
    retort = provider.get_retort()
    cryptographer = CryptographerImpl(
        SimpleNamespace(crypt_key=SecretStr("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="))
    )
    encrypted = retort.dump(cryptographer.encrypt_recursive(instance.settings))
    assert "live_test_key" not in str(encrypted) and "wh_test" not in str(encrypted)
    stored = PaymentGateway(
        id=1,
        type=PaymentGatewayType.RIVARAPAY,
        currency=Currency.RUB,
        order_index=16,
        is_active=True,
        settings=encrypted,
    )
    loaded = provider.get_conversion_retort(retort, cryptographer).get_converter(
        PaymentGateway, PaymentGatewayDto
    )(stored)
    assert isinstance(loaded.settings, RivaraGatewaySettingsDto)
    assert loaded.settings.api_key.get_secret_value() == "live_test_key"
    assert {m.id for m in loaded.settings.enabled_methods} == {"SBP", "CRYPTO"}
    saved = {
        kind: PaymentGatewayDto(type=kind, currency=Currency.from_gateway_type(kind))
        for kind in PaymentGatewayType
        if kind != PaymentGatewayType.RIVARAPAY
    }

    async def create(dto):
        saved[dto.type] = dto

    dao = SimpleNamespace(
        get_by_type=AsyncMock(side_effect=saved.get),
        get_all=AsyncMock(side_effect=lambda: list(saved.values())),
        create=AsyncMock(side_effect=create),
        update=AsyncMock(),
    )
    await CreateDefaultPaymentGateway(AsyncMock(), dao).system()
    created = saved[PaymentGatewayType.RIVARAPAY]
    assert not created.is_active and not created.settings.is_configured
    created.settings = settings()
    factory_instance = PaymentGatewaysProvider().get_gateway_factory(
        SimpleNamespace(), SimpleNamespace()
    )(created)
    assert isinstance(factory_instance, RivaraGateway)
    await factory_instance._client.aclose()


def translator():
    return FluentTranslator(
        locale="ru",
        translator=FluentBundle.from_string(
            locale="ru",
            use_isolating=False,
            text="\n".join(
                Path(f"assets/translations/ru/{name}.ftl").read_text("utf-8")
                for name in ("buttons", "messages", "utils", "notifications")
            ),
        ),
    )


async def test_checkout_buttons_cache_confirmation_and_stale_method(gateway):
    instance, _ = gateway
    enable(instance, "SBP", "CARD_RU", "CARD_INTERNATIONAL", "CRYPTO")
    retort, i18n = RetortProvider().get_retort(), translator()
    user = TelegramUserDto(id=1, telegram_id=1, name="User")
    plan = PlanDto(
        name="Тариф",
        durations=[
            PlanDurationDto(
                days=30, prices=[PlanPriceDto(currency=Currency.RUB, price=Decimal("200.10"))]
            )
        ],
    )
    manager = SimpleNamespace(
        dialog_data={
            PlanDto.__name__: retort.dump(plan),
            "selected_duration": 30,
            "purchase_type": PurchaseType.NEW,
        },
        middleware_data={
            USER_KEY: user,
            CONTAINER_KEY: SimpleNamespace(get=AsyncMock(return_value=i18n)),
        },
        start=AsyncMock(),
        switch_to=AsyncMock(),
        is_preview=lambda: False,
    )
    dao = SimpleNamespace(
        get_active=AsyncMock(return_value=[instance.data]),
        get_by_type=AsyncMock(return_value=instance.data),
    )
    pricing = SimpleNamespace(
        calculate=lambda *a, **kw: money(),
        calculate_for_duration=lambda *a, **kw: money(),
        get_effective_discount=lambda _: 0,
        is_largest_discount_personal=lambda _: False,
    )
    data = await payment_method_getter.__dishka_orig_func__(
        manager, user, retort, i18n, None, None, dao, None, pricing
    )
    keyboard = await checkout_window.find(f"{PAYMENT_PREFIX}select_payment_method").render_keyboard(
        data, manager
    )
    assert {button.callback_data.rsplit(":", 1)[-1] for row in keyboard for button in row} == {
        "SBP",
        "RU",
        "INT",
        "CRYPTO",
    }
    add_intent_id(keyboard, "12345678")
    assert all(len(button.callback_data.encode()) <= 64 for row in keyboard for button in row)
    create = AsyncMock(
        side_effect=lambda *a: SimpleNamespace(id=uuid4(), url="https://pay.rivarapay.io/test")
    )
    notifier = SimpleNamespace(notify_user=AsyncMock())
    select = on_payment_method_select.__dishka_orig_func__
    for code in ("SBP", "RU", "INT", "CRYPTO", "SBP"):
        await select(
            None, None, manager, f"RIVARAPAY:{code}", retort, dao, notifier, pricing, create
        )
    assert [call.args[1].payment_method for call in create.await_args_list] == [
        "SBP",
        "CARD_RU",
        "CARD_INTERNATIONAL",
        "CRYPTO",
    ]
    confirmed = await confirm_getter.__dishka_orig_func__(manager, user, retort, i18n, dao, pricing)
    assert confirmed["payment_method_title"] == "СБП" and not confirmed["only_single_gateway"]
    enable(instance, "ALL")
    await select(None, None, manager, "RIVARAPAY:SBP", retort, dao, notifier, pricing, create)
    assert create.await_count == 4
    notifier.notify_user.assert_awaited_once()
    assert _get_payment_options(i18n, instance.data, money()) == [
        ("RIVARAPAY:ALL", "Rivara Pay — все способы")
    ]


async def test_admin_keyboard_and_translations(gateway):
    instance, _ = gateway
    i18n = translator()
    manager = SimpleNamespace(
        dialog_data={"gateway_id": 1, "rivara_method_id": "ALL"},
        middleware_data={CONTAINER_KEY: SimpleNamespace(get=AsyncMock(return_value=i18n))},
        is_preview=lambda: False,
    )
    data = await rivara_methods_getter.__dishka_orig_func__(
        manager, SimpleNamespace(get_by_id=AsyncMock(return_value=instance.data))
    )
    keyboard = await rivara_methods.find("rivara_method").render_keyboard(data, manager)
    assert sum(len(row) for row in keyboard) == 5
    assert "Выключить" in i18n.get("btn-rivara-method-toggle", **data)
    assert "все способы" in i18n.get("msg-rivara-method", **data)
    assert i18n.get("gateway-type", gateway_type="RIVARAPAY") == "Rivara Pay"


def test_migration_includes_gateway_and_external_id():
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0057_add_rivarapay_payment_gateway"
    )
    sql = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": sql}
    )
    with Operations.context(context):
        migration.upgrade()
    assert "ADD VALUE IF NOT EXISTS 'RIVARAPAY'" in sql.getvalue()
    assert "ADD COLUMN provider_payment_id" in sql.getvalue()


@pytest.mark.parametrize("method_id", ["ALL", "SBP", "CARD_RU", "CARD_INTERNATIONAL", "CRYPTO"])
async def test_web_purchase_passes_selected_method_and_account_email(gateway, method_id):
    instance, api = gateway
    enable(instance, method_id)
    user = UserDto(id=1, name="Buyer", email="buyer@example.org", is_email_verified=True)
    plan = PlanDto(
        public_code="test-plan",
        name="Тариф",
        durations=[
            PlanDurationDto(
                days=30, prices=[PlanPriceDto(currency=Currency.RUB, price=Decimal("200.10"))]
            )
        ],
    )
    transactions = SimpleNamespace(create=AsyncMock())
    result = await web_subscription.purchase_subscription.__dishka_orig_func__(
        body=PurchaseRequest(
            plan_code="test-plan",
            duration_days=30,
            gateway_type=PaymentGatewayType.RIVARAPAY,
            payment_method=method_id,
        ),
        user=user,
        subscription_dao=SimpleNamespace(get_current=AsyncMock(return_value=None)),
        payment_gateway_dao=SimpleNamespace(get_by_type=AsyncMock(return_value=instance.data)),
        pricing_service=SimpleNamespace(calculate=lambda *a, **kw: money()),
        get_available_plans=SimpleNamespace(system=AsyncMock(return_value=[plan])),
        create_payment=create_service(instance, transactions),
        process_payment=AsyncMock(),
    )
    assert result.payment_url.startswith("https://pay.rivarapay.io/")
    assert transactions.create.await_args.args[0].payment_method == method_id
    assert json.loads(api.requests[0].content)["customerEmail"] == "buyer@example.org"
    assert [method.id for method in web_subscription._web_payment_methods(instance.data)] == [
        method_id
    ]


async def test_web_purchase_requires_an_enabled_unambiguous_method(gateway):
    instance, _ = gateway
    enable(instance, "SBP", "CRYPTO")
    dao = SimpleNamespace(get_by_type=AsyncMock(return_value=instance.data))
    for method_id in (None, "CARD_RU", "ALL"):
        with pytest.raises(HTTPException) as error:
            await web_subscription._validate_gateway_for_web(
                PaymentGatewayType.RIVARAPAY, dao, method_id
            )
        assert error.value.status_code == 400
