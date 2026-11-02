import asyncio
import hashlib
import hmac
import importlib
import io
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import orjson
import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fluent_compiler.bundle import FluentBundle
from fluentogram.translator import FluentTranslator
from httpx import AsyncClient, HTTPStatusError, MockTransport, Response
from pydantic import SecretStr
from starlette.requests import Request

from src.application.dto import (
    PaymentGatewayDto,
    PlanSnapshotDto,
    PriceDetailsDto,
    TransactionDto,
    UserDto,
)
from src.application.dto.payment_gateway import FlippayGatewaySettingsDto
from src.application.use_cases.gateways.commands.configuration import (
    UpdatePaymentGatewaySettings,
    UpdatePaymentGatewaySettingsDto,
)
from src.application.use_cases.gateways.commands.payment import (
    CreateDefaultPaymentGateway,
    ProcessPayment,
    ProcessPaymentDto,
)
from src.application.use_cases.gateways.commands.recheck import RecheckPayment, can_recheck_payment
from src.core.enums import Currency, PaymentGatewayType, PurchaseType, Role, TransactionStatus
from src.infrastructure.database.models import PaymentGateway
from src.infrastructure.di.providers.payment_gateways import PaymentGatewaysProvider
from src.infrastructure.di.providers.retort import RetortProvider
from src.infrastructure.payment_gateways import FlippayGateway
from src.infrastructure.services.cryptography import CryptographerImpl
from src.web.endpoints import payments


def settings():
    return FlippayGatewaySettingsDto(
        api_key=SecretStr("pk_test"),
        api_secret=SecretStr("sk_test"),
        webhook_secret=SecretStr("wh_test"),
    )


def transaction(**changes):
    return TransactionDto(
        payment_id=changes.pop("payment_id", uuid4()),
        user_id=1,
        status=changes.pop("status", TransactionStatus.PENDING),
        purchase_type=PurchaseType.NEW,
        gateway_type=changes.pop("gateway_type", PaymentGatewayType.FLIPPAY),
        pricing=PriceDetailsDto(
            original_amount=Decimal("200"), discount_percent=0, final_amount=Decimal("200")
        ),
        currency=Currency.RUB,
        plan_snapshot=PlanSnapshotDto.test(),
        **changes,
    )


def payload(tx, **changes):
    return {
        "event": "payment.updated",
        "order_id": str(tx.payment_id),
        "status": "success",
        "amount": "200.00",
        "customer_amount": "210.00",
        "customer_fee": "10.00",
        "currency": "RUB",
        **changes,
    }


def request(data, *, valid=True, raw_body=None, signature=None):
    body = raw_body if raw_body is not None else orjson.dumps(data)
    if signature is None:
        signature = hmac.new(b"wh_test" if valid else b"sk_test", body, hashlib.sha256).hexdigest()
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [(b"x-signature", signature.encode())],
        },
        receive=AsyncMock(return_value={"type": "http.request", "body": body, "more_body": False}),
    )


@pytest.fixture
async def gateway():
    dto = PaymentGatewayDto(
        type=PaymentGatewayType.FLIPPAY, currency=Currency.RUB, is_active=True, settings=settings()
    )
    bot = SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username="test_bot")))
    instance = FlippayGateway(dto, bot, SimpleNamespace())
    headers = instance._client.headers
    await instance._client.aclose()
    api = SimpleNamespace(requests=[], response=None, status=200)

    def respond(req):
        api.requests.append(req)
        if api.response is not None:
            return Response(api.status, json=api.response)
        data = json.loads(req.content)
        return Response(
            200, json={**data, "status": "pending", "pay_url": "https://eaglors.com/pay/test"}
        )

    async with AsyncClient(
        base_url=instance.API_BASE, headers=headers, transport=MockTransport(respond)
    ) as client:
        instance._client = client
        yield instance, api


@pytest.mark.parametrize("method", [100, 101, 103, 777])
async def test_creation_uses_documented_headers_money_format_and_returned_url(gateway, method):
    instance, api = gateway
    instance.settings.payment_method = method
    result = await instance.handle_create_payment(Decimal("200.10"), "Тариф на месяц")
    req = api.requests[0]
    assert req.method == "POST"
    assert req.url == "https://flippay.pro/api/v1/payments"
    assert req.headers["X-Api-Key"] == "pk_test"
    assert req.headers["X-Api-Secret"] == "sk_test"
    data = json.loads(req.content)
    assert data == {
        "order_id": str(result.id),
        "amount": "200.10",
        "currency": "RUB",
        "payment_method": method,
        "description": "Тариф на месяц",
        "success_url": "https://t.me/test_bot",
        "fail_url": "https://t.me/test_bot",
    }
    assert result.url == "https://eaglors.com/pay/test"
    assert isinstance(result.id, UUID)


@pytest.mark.parametrize("amount", ["0", "-1", "1.001", "NaN", "Infinity"])
async def test_invalid_amount_never_reaches_api(gateway, amount):
    instance, api = gateway
    with pytest.raises(ValueError):
        await instance.handle_create_payment(Decimal(amount), "VPN")
    assert not api.requests


async def test_creation_rejects_mismatched_order_and_api_failure(gateway):
    instance, api = gateway
    api.response = {"order_id": str(uuid4()), "pay_url": "https://example.com/pay"}
    with pytest.raises(ValueError, match="order ID mismatch"):
        await instance.handle_create_payment(Decimal(200), "VPN")
    api.status = 401
    with pytest.raises(HTTPStatusError):
        await instance.handle_create_payment(Decimal(200), "VPN")


@pytest.mark.parametrize(
    "status,expected",
    [
        ("success", TransactionStatus.COMPLETED),
        ("failed", TransactionStatus.FAILED),
        ("refunded", TransactionStatus.REFUNDED),
    ],
)
async def test_signed_callbacks_map_payment_statuses(gateway, status, expected):
    instance, _ = gateway
    tx = transaction()
    data = payload(tx, status=status)
    assert await instance.handle_webhook(request(data)) == (tx.payment_id, expected)


async def test_signature_uses_original_bytes_and_separate_webhook_secret(gateway):
    instance, _ = gateway
    tx = transaction()
    data = payload(tx, metadata={"description": "Подписка"})
    raw = json.dumps(data, ensure_ascii=False, indent=2).encode()
    assert await instance.handle_webhook(request(data, raw_body=raw))
    with pytest.raises(PermissionError):
        await instance.handle_webhook(request(data, valid=False))
    signature = hmac.new(b"wh_test", raw, hashlib.sha256).hexdigest()
    with pytest.raises(PermissionError):
        await instance.handle_webhook(request(data, signature=signature))


@pytest.mark.parametrize("signature", ["", "wrong", "я" * 64, "a" * 63])
async def test_missing_or_malformed_signature_is_rejected(gateway, signature):
    instance, _ = gateway
    with pytest.raises(PermissionError):
        await instance.handle_webhook(request(payload(transaction()), signature=signature))


def webhook_dependencies(instance, tx):
    return {
        "gateway_type": "flippay",
        "config": SimpleNamespace(build=SimpleNamespace(data={})),
        "event_publisher": SimpleNamespace(publish=AsyncMock()),
        "get_payment_gateway_instance": SimpleNamespace(
            for_webhook=AsyncMock(return_value=instance)
        ),
        "transaction_dao": SimpleNamespace(get_by_payment_id=AsyncMock(return_value=tx)),
        "uow": AsyncMock(),
        "autopay": SimpleNamespace(),
    }


async def test_callback_checks_merchant_amount_without_enabling_recovery(gateway, monkeypatch):
    instance, _ = gateway
    tx = transaction(status=TransactionStatus.CANCELED)
    enqueue = AsyncMock()
    monkeypatch.setattr(payments.handle_payment_transaction_task, "kiq", enqueue)
    response = await payments._process_payment_webhook(
        request=request(payload(tx)), **webhook_dependencies(instance, tx)
    )
    assert response.status_code == 200
    enqueue.assert_awaited_once_with(
        tx.payment_id,
        TransactionStatus.COMPLETED,
        PaymentGatewayType.FLIPPAY,
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"amount": "199.99"},
        {"amount": "210.00"},
        {"currency": "USD"},
        {"event": "other"},
        {"status": "pending"},
        {"status": []},
        {"amount": None},
        {"order_id": "not-a-uuid"},
    ],
)
async def test_invalid_callback_never_enqueues_purchase(gateway, monkeypatch, patch):
    instance, _ = gateway
    tx = transaction()
    enqueue = AsyncMock()
    monkeypatch.setattr(payments.handle_payment_transaction_task, "kiq", enqueue)
    response = await payments._process_payment_webhook(
        request=request(payload(tx, **patch)), **webhook_dependencies(instance, tx)
    )
    assert response.status_code == 400
    enqueue.assert_not_awaited()


async def test_wrong_signature_wrong_gateway_and_unsaved_order_are_not_acknowledged(
    gateway, monkeypatch
):
    instance, _ = gateway
    tx = transaction()
    enqueue = AsyncMock()
    monkeypatch.setattr(payments.handle_payment_transaction_task, "kiq", enqueue)
    deps = webhook_dependencies(instance, tx)
    response = await payments._process_payment_webhook(
        request=request(payload(tx), valid=False), **deps
    )
    assert response.status_code == 403
    deps["transaction_dao"].get_by_payment_id.return_value = replace(
        tx, gateway_type=PaymentGatewayType.PLATEGA
    )
    response = await payments._process_payment_webhook(request=request(payload(tx)), **deps)
    assert response.status_code == 400
    deps["transaction_dao"].get_by_payment_id.return_value = None
    response = await payments._process_payment_webhook(request=request(payload(tx)), **deps)
    assert response.status_code == 503
    enqueue.assert_not_awaited()


async def test_queue_outage_requests_webhook_retry(gateway, monkeypatch):
    instance, _ = gateway
    tx = transaction()
    monkeypatch.setattr(
        payments.handle_payment_transaction_task,
        "kiq",
        AsyncMock(side_effect=RuntimeError("Redis unavailable")),
    )
    response = await payments._process_payment_webhook(
        request=request(payload(tx)), **webhook_dependencies(instance, tx)
    )
    assert response.status_code == 503


async def test_shared_gateway_does_not_mix_concurrent_callbacks(gateway, monkeypatch):
    instance, _ = gateway
    transactions = {tx.payment_id: tx for tx in [transaction(), transaction()]}
    enqueue = AsyncMock()
    monkeypatch.setattr(payments.handle_payment_transaction_task, "kiq", enqueue)
    deps = webhook_dependencies(instance, None)
    deps["transaction_dao"].get_by_payment_id.side_effect = transactions.get
    responses = await asyncio.gather(
        *[
            payments._process_payment_webhook(request=request(payload(tx)), **deps)
            for tx in transactions.values()
        ]
    )
    assert all(response.status_code == 200 for response in responses)
    assert {call.args[0] for call in enqueue.await_args_list} == set(transactions)


async def test_canceled_payment_requires_manual_recheck_before_fulfillment(gateway, monkeypatch):
    instance, api = gateway
    tx = transaction(status=TransactionStatus.CANCELED)
    api.response = payload(tx)

    async def transition(payment_id, status, allowed):
        if tx.status not in allowed:
            return None
        tx.status = status
        return tx

    dao = SimpleNamespace(
        get_by_payment_id=AsyncMock(return_value=tx),
        transition_status=AsyncMock(side_effect=transition),
    )
    process = ProcessPayment.__new__(ProcessPayment)
    process.uow = AsyncMock()
    process.transaction_dao = dao
    process.user_dao = SimpleNamespace(
        get_by_id=AsyncMock(return_value=UserDto(id=1, name="Buyer"))
    )
    process._handle_success = AsyncMock()
    worker = payments.handle_payment_transaction_task.original_func.__dishka_orig_func__

    async def enqueue(*args, **kwargs):
        await worker(*args, process_payment=process, **kwargs)

    monkeypatch.setattr(
        payments.handle_payment_transaction_task, "kiq", AsyncMock(side_effect=enqueue)
    )
    deps = webhook_dependencies(instance, tx)
    deps["transaction_dao"] = dao
    response = await payments._process_payment_webhook(request=request(payload(tx)), **deps)
    assert response.status_code == 200
    assert tx.status == TransactionStatus.CANCELED
    process._handle_success.assert_not_awaited()

    recheck = RecheckPayment(
        dao, SimpleNamespace(for_webhook=AsyncMock(return_value=instance)), process
    )
    actor = UserDto(id=2, name="Admin", role=Role.ADMIN)
    assert can_recheck_payment(tx)
    result = await recheck(actor, tx.payment_id)
    assert result.is_paid and result.processed
    assert api.requests[0].url.path == f"/api/v1/payments/{tx.payment_id}"
    assert not (await recheck(actor, tx.payment_id)).processed
    assert not await process.system(
        ProcessPaymentDto(
            tx.payment_id,
            TransactionStatus.COMPLETED,
            PaymentGatewayType.FLIPPAY,
        )
    )
    process._handle_success.assert_awaited_once()


@pytest.mark.parametrize(
    "patch", [{"amount": "199.00"}, {"currency": "USD"}, {"order_id": str(uuid4())}]
)
async def test_recheck_rejects_mismatched_payment(gateway, patch):
    instance, api = gateway
    tx = transaction(status=TransactionStatus.CANCELED)
    api.response = payload(tx, **patch)
    process = SimpleNamespace(system=AsyncMock())
    recheck = RecheckPayment(
        SimpleNamespace(get_by_payment_id=AsyncMock(return_value=tx)),
        SimpleNamespace(for_webhook=AsyncMock(return_value=instance)),
        process,
    )
    with pytest.raises(ValueError):
        await recheck(UserDto(name="Admin", role=Role.ADMIN), tx.payment_id)
    process.system.assert_not_awaited()


async def test_settings_secrets_round_trip_through_encrypted_storage():
    provider = RetortProvider()
    retort = provider.get_retort()
    cryptographer = CryptographerImpl(
        SimpleNamespace(crypt_key=SecretStr("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="))
    )
    config = settings()
    config.payment_timeout_minutes = 90
    encrypted = retort.dump(cryptographer.encrypt_recursive(config))
    assert "sk_test" not in str(encrypted) and "wh_test" not in str(encrypted)
    stored = PaymentGateway(
        id=1,
        type=PaymentGatewayType.FLIPPAY,
        currency=Currency.RUB,
        order_index=15,
        is_active=True,
        settings=encrypted,
    )
    loaded = provider.get_conversion_retort(retort, cryptographer).get_converter(
        PaymentGateway, PaymentGatewayDto
    )(stored)
    assert isinstance(loaded.settings, FlippayGatewaySettingsDto)
    assert loaded.settings.api_secret.get_secret_value() == "sk_test"
    assert loaded.settings.webhook_secret.get_secret_value() == "wh_test"
    assert loaded.settings.payment_timeout_minutes == 90
    assert loaded.settings.is_configured
    # Existing gateway JSON without a timeout field uses the new default of 60.
    stored.settings = {
        key: value for key, value in encrypted.items() if key != "payment_timeout_minutes"
    }
    loaded = provider.get_conversion_retort(retort, cryptographer).get_converter(
        PaymentGateway, PaymentGatewayDto
    )(stored)
    assert loaded.settings.payment_timeout_minutes == 60


async def test_startup_adds_inactive_gateway_and_factory_constructs_it():
    saved = {
        kind: PaymentGatewayDto(type=kind, currency=Currency.from_gateway_type(kind))
        for kind in PaymentGatewayType
        if kind != PaymentGatewayType.FLIPPAY
    }

    async def create(dto):
        saved[dto.type] = dto
        return dto

    dao = SimpleNamespace(
        get_by_type=AsyncMock(side_effect=saved.get),
        get_all=AsyncMock(side_effect=lambda: list(saved.values())),
        create=AsyncMock(side_effect=create),
        update=AsyncMock(),
    )
    await CreateDefaultPaymentGateway(AsyncMock(), dao).system()
    created = saved[PaymentGatewayType.FLIPPAY]
    assert not created.is_active and created.currency == Currency.RUB
    assert isinstance(created.settings, FlippayGatewaySettingsDto)
    assert created.settings.payment_method == 100 and not created.settings.is_configured
    created.settings = settings()
    instance = PaymentGatewaysProvider().get_gateway_factory(SimpleNamespace(), SimpleNamespace())(
        created
    )
    assert isinstance(instance, FlippayGateway)
    await instance._client.aclose()


@pytest.mark.parametrize("value", ["0", "-1"])
async def test_settings_reject_invalid_method_ids(value):
    dto = PaymentGatewayDto(
        type=PaymentGatewayType.FLIPPAY, currency=Currency.RUB, settings=settings()
    )
    dao = SimpleNamespace(get_by_id=AsyncMock(return_value=dto), update=AsyncMock())
    service = UpdatePaymentGatewaySettings(AsyncMock(), dao, RetortProvider().get_retort())
    with pytest.raises(ValueError):
        await service.system(UpdatePaymentGatewaySettingsDto(1, "payment_method", value))
    dao.update.assert_not_awaited()


def test_migration_and_gateway_label():
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0055_add_flippay_payment_gateway"
    )
    sql = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": sql}
    )
    with Operations.context(context):
        migration.upgrade()
    assert "ALTER TYPE payment_gateway_type ADD VALUE IF NOT EXISTS 'FLIPPAY'" in sql.getvalue()
    translator = FluentTranslator(
        locale="ru",
        translator=FluentBundle.from_string(
            locale="ru",
            text=Path("assets/translations/ru/utils.ftl").read_text("utf-8"),
            use_isolating=False,
        ),
    )
    assert translator.get("gateway-type", gateway_type="FLIPPAY") == "FlipPay"
