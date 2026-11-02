import asyncio
import hashlib
import hmac
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import orjson
import pytest
from fluent_compiler.bundle import FluentBundle
from fluentogram.translator import FluentTranslator
from httpx import AsyncClient, HTTPStatusError, MockTransport, Response
from pydantic import SecretStr
from starlette.requests import Request

from src.application.dto import PaymentGatewayDto, PlanDto, PlanSnapshotDto, PriceDetailsDto
from src.application.dto.payment_gateway import FlippayGatewaySettingsDto, FlippayPaymentMethodDto
from src.application.dto.plan import PlanDurationDto, PlanPriceDto
from src.application.dto.user import TelegramUserDto, UserDto
from src.application.use_cases.gateways.commands.flippay_methods import (
    RefreshFlippayPaymentMethods,
    UpdateFlippayPaymentMethod,
    UpdateFlippayPaymentMethodDto,
)
from src.application.use_cases.gateways.commands.payment import (
    CreatePayment,
    CreatePaymentDto,
    CreateTestPayment,
)
from src.application.use_cases.gateways.queries.providers import GetPaymentGatewayInstance
from src.core.constants import CONTAINER_KEY, PAYMENT_PREFIX, USER_KEY
from src.core.enums import Currency, PaymentGatewayType, PurchaseType, TransactionStatus
from src.core.exceptions import PermissionDeniedError
from src.infrastructure.database.dao.base import BaseDaoImpl
from src.infrastructure.database.models import PaymentGateway
from src.infrastructure.di.providers.retort import RetortProvider
from src.infrastructure.payment_gateways import FlippayGateway
from src.infrastructure.services.cryptography import CryptographerImpl
from src.telegram.routers.dashboard.remnashop.gateways.dialog import (
    flippay_methods as methods_window,
)
from src.telegram.routers.dashboard.remnashop.gateways.flippay_methods import flippay_methods_getter
from src.telegram.routers.subscription.dialog import payment_method as checkout_window
from src.telegram.routers.subscription.getters import (
    _get_payment_options,
    confirm_getter,
    payment_method_getter,
)
from src.telegram.routers.subscription.handlers import on_payment_method_select


def method(method_id, code, name, **kwargs):
    return FlippayPaymentMethodDto(id=method_id, code=code, name=name, **kwargs)


def money(amount="200"):
    return PriceDetailsDto(
        original_amount=Decimal(amount), final_amount=Decimal(amount), discount_percent=0
    )


@pytest.fixture
async def gateway():
    settings = FlippayGatewaySettingsDto(
        api_key=SecretStr("pk_test"),
        api_secret=SecretStr("sk_test"),
        webhook_secret=SecretStr("wh_test"),
        methods=[
            method(100, "sbp", "СБП", display_name="Банки РФ", enabled=True),
            method(
                101,
                "card",
                "Карты МИР",
                min_amount=Decimal("100"),
                display_name="Оплата картой",
                enabled=True,
            ),
            method(103, "crypto", "Криптовалюта"),
        ],
    )
    dto = PaymentGatewayDto(
        id=1,
        type=PaymentGatewayType.FLIPPAY,
        currency=Currency.RUB,
        settings=settings,
        is_active=True,
    )
    instance = FlippayGateway(
        dto,
        SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username="test_bot"))),
        SimpleNamespace(),
    )
    headers = instance._client.headers
    await instance._client.aclose()
    api = SimpleNamespace(
        requests=[],
        status=200,
        methods=[
            {"id": 100, "code": "sbp", "name": "СБП", "min_amount": "0.01"},
            {"id": 101, "code": "card", "name": "Карты МИР", "min_amount": "100.00"},
            {"id": 103, "code": "crypto", "name": "Криптовалюта", "min_amount": "10.00"},
        ],
    )

    def respond(request):
        api.requests.append(request)
        if request.method == "GET":
            return Response(api.status, json=api.methods)
        data = json.loads(request.content)
        return Response(
            200, json={**data, "pay_url": f"https://example.org/pay/{data['order_id']}"}
        )

    async with AsyncClient(
        base_url=instance.API_BASE, headers=headers, transport=MockTransport(respond)
    ) as client:
        instance._client = client
        yield instance, api


def refresh_service(instance):
    dao = SimpleNamespace(get_by_id=AsyncMock(return_value=instance.data), update=AsyncMock())
    return RefreshFlippayPaymentMethods(AsyncMock(), dao, lambda _: instance), dao


async def test_refresh_preserves_names_toggles_by_code_when_ids_change(gateway):
    instance, api = gateway
    api.methods[0]["id"] = 201
    api.methods.pop(1)  # The card method has disappeared from the merchant account.
    api.methods.append({"id": 777, "code": "new", "name": "Новый", "min_amount": "5"})
    refresh, dao = refresh_service(instance)
    assert await refresh.system(1) == 3
    by_code = {entry.code: entry for entry in instance.settings.methods}
    assert by_code["sbp"].id == 201
    assert by_code["sbp"].title == "Банки РФ" and by_code["sbp"].enabled
    assert not by_code["new"].enabled
    assert not by_code["card"].available
    assert {entry.id for entry in instance.settings.enabled_methods} == {201}
    dao.update.assert_awaited_once()
    request = api.requests[0]
    assert request.url.path == "/api/v1/payment-methods"
    assert request.headers["X-Api-Key"] == "pk_test"
    assert request.headers["X-Api-Secret"] == "sk_test"
    # A temporarily removed method retains its settings when it comes back.
    api.methods.append({"id": 301, "code": "card", "name": "МИР", "min_amount": "100"})
    await refresh.system(1)
    restored = instance.settings.get_payment_method(301)
    assert restored.title == "Оплата картой" and restored.available


async def test_refresh_keeps_legacy_single_method_and_enables_no_new_methods(gateway):
    instance, _ = gateway
    instance.settings.methods = None
    instance.settings.payment_method = 101
    instance.settings.display_name = "Моя карта"
    refresh, _ = refresh_service(instance)
    await refresh.system(1)
    assert [entry.id for entry in instance.settings.enabled_methods] == [101]
    assert instance.settings.get_payment_method(101).title == "Моя карта"


async def test_reused_id_with_different_code_does_not_inherit_enabled_status(gateway):
    instance, api = gateway
    api.methods = [{"id": 100, "code": "different", "name": "Другой", "min_amount": "1"}]
    refresh, _ = refresh_service(instance)
    await refresh.system(1)
    assert not instance.settings.enabled_methods


@pytest.mark.parametrize(
    "response",
    [
        {},
        [{"id": "100", "code": "sbp", "name": "СБП", "min_amount": "1"}],
        [{"id": 0, "code": "sbp", "name": "СБП", "min_amount": "1"}],
        [{"id": 100, "code": "", "name": "СБП", "min_amount": "1"}],
        [{"id": 100, "code": "sbp", "name": "", "min_amount": "1"}],
        [{"id": 100, "code": "sbp", "name": "СБП", "min_amount": "NaN"}],
        [{"id": 100, "code": "sbp", "name": "СБП", "min_amount": "-1"}],
        [{"id": 100, "code": "sbp", "name": "СБП"}],
        [{"id": 100, "code": "sbp", "name": "СБП", "min_amount": "1"}] * 2,
    ],
)
async def test_bad_api_response_never_replaces_saved_methods(gateway, response):
    instance, api = gateway
    previous = instance.settings.methods
    api.methods = response
    refresh, dao = refresh_service(instance)
    with pytest.raises(ValueError):
        await refresh.system(1)
    assert instance.settings.methods == previous
    dao.update.assert_not_awaited()


async def test_api_error_never_replaces_saved_methods(gateway):
    instance, api = gateway
    api.status = 401
    refresh, dao = refresh_service(instance)
    with pytest.raises(HTTPStatusError):
        await refresh.system(1)
    dao.update.assert_not_awaited()


async def test_admin_edits_persist_in_json_with_credentials_and_old_json_still_loads(gateway):
    instance, _ = gateway
    dao = SimpleNamespace(get_by_id=AsyncMock(return_value=instance.data), update=AsyncMock())
    edit = UpdateFlippayPaymentMethod(AsyncMock(), dao)
    await edit.system(UpdateFlippayPaymentMethodDto(1, 100, "rename", "  Мои банки  "))
    await edit.system(UpdateFlippayPaymentMethodDto(1, 101, "toggle"))
    assert instance.settings.get_payment_method(100).title == "Мои банки"
    assert [entry.id for entry in instance.settings.enabled_methods] == [100]
    provider = RetortProvider()
    retort = provider.get_retort()
    crypt = CryptographerImpl(
        SimpleNamespace(crypt_key=SecretStr("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="))
    )
    stored = PaymentGateway(
        id=1,
        type=PaymentGatewayType.FLIPPAY,
        currency=Currency.RUB,
        order_index=1,
        is_active=True,
        settings=retort.dump(crypt.encrypt_recursive(instance.settings)),
    )
    convert = provider.get_conversion_retort(retort, crypt).get_converter(
        PaymentGateway, PaymentGatewayDto
    )
    loaded = convert(stored)
    assert loaded.settings.api_secret.get_secret_value() == "sk_test"
    assert loaded.settings.get_payment_method(100).title == "Мои банки"
    assert isinstance(loaded.settings.methods[1].min_amount, Decimal)
    assert not loaded.settings.methods[1].enabled
    serializer = BaseDaoImpl(None, retort)
    changes = serializer._serialize_for_update(
        instance.data, PaymentGatewayDto, PaymentGateway, pre_process=crypt.encrypt_recursive
    )
    # The DAO merges the complete methods array into settings, preserving credential keys.
    partial = next(
        value for value in changes["settings"].compile().params.values() if isinstance(value, dict)
    )
    assert partial["methods"][0]["display_name"] == "Мои банки"
    assert partial["methods"][1]["enabled"] is False
    await edit.system(UpdateFlippayPaymentMethodDto(1, 100, "reset_name"))
    assert instance.settings.get_payment_method(100).title == "СБП"
    stored.settings.pop("methods")
    assert convert(stored).settings.get_payment_method().id == 100


async def test_method_edits_require_admin_permission_and_nonempty_name(gateway):
    instance, _ = gateway
    dao = SimpleNamespace(get_by_id=AsyncMock(return_value=instance.data), update=AsyncMock())
    edit = UpdateFlippayPaymentMethod(AsyncMock(), dao)
    with pytest.raises(PermissionDeniedError):
        await edit(UserDto(name="User"), UpdateFlippayPaymentMethodDto(1, 100, "toggle"))
    with pytest.raises(ValueError):
        await edit.system(UpdateFlippayPaymentMethodDto(1, 100, "rename", " "))
    instance.settings.methods = [replace(instance.settings.methods[2], available=False)]
    with pytest.raises(ValueError):
        await edit.system(UpdateFlippayPaymentMethodDto(1, 103, "toggle"))
    dao.update.assert_not_awaited()


async def test_concurrent_checkouts_use_selected_method_and_save_its_title(gateway):
    instance, api = gateway
    transactions = SimpleNamespace(create=AsyncMock())
    create = CreatePayment(
        AsyncMock(),
        None,
        transactions,
        SimpleNamespace(system=AsyncMock(return_value=instance)),
        SimpleNamespace(
            get_translator_by_locale=lambda _: SimpleNamespace(get=lambda *a, **kw: "Тариф")
        ),
    )
    await asyncio.gather(
        *(
            create.system(
                CreatePaymentDto(
                    plan_snapshot=PlanSnapshotDto.test(),
                    pricing=money(),
                    purchase_type=PurchaseType.NEW,
                    gateway_type=PaymentGatewayType.FLIPPAY,
                    payment_method=method_id,
                )
            )
            for method_id in (100, 101)
        )
    )
    assert {json.loads(request.content)["payment_method"] for request in api.requests} == {100, 101}
    saved = [call.args[0] for call in transactions.create.await_args_list]
    assert {(tx.payment_method, tx.gateway_display_name) for tx in saved} == {
        ("100", "Банки РФ"),
        ("101", "Оплата картой"),
    }
    assert instance.settings.payment_method == 100


@pytest.mark.parametrize(
    "method_id,amount", [(103, "200"), (999, "200"), (101, "99.99"), (None, "200")]
)
async def test_disabled_unknown_ambiguous_or_too_small_checkout_never_calls_api(
    gateway, method_id, amount
):
    instance, api = gateway
    with pytest.raises(ValueError):
        await instance.handle_create_payment(Decimal(amount), "Тариф", payment_method=method_id)
    assert not api.requests


async def test_test_invoice_respects_method_minimum_and_persists_name(gateway):
    instance, api = gateway
    instance.settings.methods = [instance.settings.methods[1]]
    transactions = SimpleNamespace(create=AsyncMock())
    create = CreateTestPayment(
        AsyncMock(),
        None,
        transactions,
        SimpleNamespace(system=AsyncMock(return_value=instance)),
        SimpleNamespace(
            get_translator_by_locale=lambda _: SimpleNamespace(get=lambda *a, **kw: "Тест")
        ),
    )
    await create.system(PaymentGatewayType.FLIPPAY)
    assert json.loads(api.requests[0].content)["amount"] == "100.00"
    tx = transactions.create.await_args.args[0]
    assert tx.payment_method == "101" and tx.gateway_display_name == "Оплата картой"


async def test_disabled_gateway_with_all_methods_off_still_accepts_signed_webhook(gateway):
    instance, _ = gateway
    instance.data.is_active = False
    instance.settings.methods = [
        replace(entry, enabled=False) for entry in instance.settings.methods
    ]
    provider = GetPaymentGatewayInstance(
        AsyncMock(),
        SimpleNamespace(get_by_type=AsyncMock(return_value=instance.data)),
        lambda _: instance,
    )
    webhook_gateway = await provider.for_webhook(PaymentGatewayType.FLIPPAY)
    payment_id = uuid4()
    body = orjson.dumps(
        {
            "event": "payment.updated",
            "order_id": str(payment_id),
            "amount": "200",
            "currency": "RUB",
            "status": "success",
        }
    )
    signature = hmac.new(b"wh_test", body, hashlib.sha256).hexdigest()
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [(b"x-signature", signature.encode())],
        },
        receive=AsyncMock(return_value={"type": "http.request", "body": body}),
    )
    assert await webhook_gateway.handle_webhook(request) == (
        payment_id,
        TransactionStatus.COMPLETED,
    )


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


async def test_checkout_buttons_cache_and_confirmation_keep_methods_separate(gateway):
    instance, _ = gateway
    retort = RetortProvider().get_retort()
    user = TelegramUserDto(id=1, telegram_id=1, name="User")
    plan = PlanDto(
        name="Тариф",
        durations=[
            PlanDurationDto(
                days=30, prices=[PlanPriceDto(currency=Currency.RUB, price=Decimal("200"))]
            )
        ],
    )
    i18n = translator()
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
        calculate=lambda *args, **kwargs: money(),
        calculate_for_duration=lambda *args, **kwargs: money(),
        get_effective_discount=lambda _: 0,
        is_largest_discount_personal=lambda _: False,
    )
    data = await payment_method_getter.__dishka_orig_func__(
        manager, user, retort, i18n, None, None, dao, None, pricing
    )
    assert [entry["gateway_title"] for entry in data["payment_methods"]] == [
        "Банки РФ",
        "Оплата картой",
    ]
    keyboard = await checkout_window.find(f"{PAYMENT_PREFIX}select_payment_method").render_keyboard(
        data, manager
    )
    assert {button.callback_data.rsplit(":", 2)[-1] for row in keyboard for button in row} == {
        "100",
        "101",
    }
    create = AsyncMock(
        side_effect=lambda *args: SimpleNamespace(id=uuid4(), url="https://example.org/pay")
    )
    notifier = SimpleNamespace(notify_user=AsyncMock())
    select = on_payment_method_select.__dishka_orig_func__
    for method_id in (100, 101, 100):
        await select(
            None, None, manager, f"FLIPPAY:{method_id}", retort, dao, notifier, pricing, create
        )
    assert create.await_count == 2
    assert [call.args[1].payment_method for call in create.await_args_list] == [100, 101]
    confirmed = await confirm_getter.__dishka_orig_func__(manager, user, retort, i18n, dao, pricing)
    assert confirmed["payment_method_title"] == "Банки РФ"
    assert not confirmed["only_single_gateway"]
    # An old button must not reopen even a cached invoice after its method is disabled.
    instance.settings.methods = [
        replace(entry, enabled=False) for entry in instance.settings.methods
    ]
    await select(None, None, manager, "FLIPPAY:100", retort, dao, notifier, pricing, create)
    assert create.await_count == 2
    notifier.notify_user.assert_awaited_once()


async def test_admin_methods_screen_and_minimum_amount_filter(gateway):
    instance, _ = gateway
    i18n = translator()
    manager = SimpleNamespace(
        dialog_data={"gateway_id": 1, "flippay_method_id": 100},
        middleware_data={CONTAINER_KEY: SimpleNamespace(get=AsyncMock(return_value=i18n))},
        is_preview=lambda: False,
    )
    data = await flippay_methods_getter.__dishka_orig_func__(
        manager, SimpleNamespace(get_by_id=AsyncMock(return_value=instance.data))
    )
    keyboard = await methods_window.find("flippay_method").render_keyboard(data, manager)
    assert sum(len(row) for row in keyboard) == 3
    assert "Банки РФ" in keyboard[0][0].text
    assert "Название для покупателя: Банки РФ" in i18n.get("msg-flippay-method", **data)
    assert "Выключить" in i18n.get("btn-flippay-method-toggle", **data)

    assert _get_payment_options(i18n, instance.data, money("99.99")) == [
        ("FLIPPAY:100", "Банки РФ")
    ]
