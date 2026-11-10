import base64
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from xml.etree.ElementTree import fromstring

import httpx
import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import CreateInvoiceLink
from fluent_compiler.bundle import FluentBundle
from fluentogram.translator import FluentTranslator
from pydantic import SecretStr

from src.application.dto import PaymentGatewayDto
from src.application.dto.payment_gateway import ValutixGatewaySettingsDto
from src.application.events import ErrorEvent
from src.core.enums import Currency, PaymentGatewayType
from src.infrastructure.di.providers.retort import RetortProvider
from src.infrastructure.payment_gateways import base
from src.infrastructure.payment_gateways.base import BasePaymentGateway
from src.infrastructure.payment_gateways.diagnostics import (
    PAYMENT_GATEWAY_EXTENSION,
    find_payment_gateway_timeout,
)
from src.infrastructure.payment_gateways.telegram_stars import TelegramStarsGateway
from src.infrastructure.payment_gateways.valutix import ValutixGateway
from src.infrastructure.services.notification import NotificationService
from src.infrastructure.services.translator import TranslatorRunnerImpl


class StubGateway(BasePaymentGateway):
    async def handle_create_payment(self, amount, details):
        raise NotImplementedError

    async def handle_webhook(self, request):
        raise NotImplementedError


def mock_gateway_client(monkeypatch, error, gateway_type=PaymentGatewayType.VALUTIX):
    def fail(request):
        raise error

    def make_client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(fail), trust_env=False, **kwargs)

    monkeypatch.setattr(base, "AsyncClient", make_client)
    gateway = StubGateway(
        PaymentGatewayDto(type=gateway_type, currency=Currency.RUB),
        SimpleNamespace(),
        SimpleNamespace(),
    )
    return gateway._make_client("https://api.example.com")


@pytest.mark.parametrize(
    "gateway_type",
    [
        kind
        for kind in PaymentGatewayType
        if kind not in {PaymentGatewayType.TELEGRAM_STARS, PaymentGatewayType.ROBOKASSA}
    ],
)
async def test_shared_client_identifies_gateway_without_changing_exception(
    monkeypatch, gateway_type
):
    error = httpx.ConnectTimeout("")
    async with mock_gateway_client(monkeypatch, error, gateway_type) as client:
        with pytest.raises(httpx.ConnectTimeout) as raised:
            await client.post("v1/orders")

    assert raised.value is error
    assert str(error) == ""
    diagnostic = find_payment_gateway_timeout(error)
    assert diagnostic.gateway_type == gateway_type
    assert diagnostic.error_type == "ConnectTimeout"
    assert diagnostic.phase == "connect"
    assert diagnostic.timeout_seconds == 30
    assert diagnostic.method == "POST"
    assert diagnostic.host == "api.example.com"


@pytest.mark.parametrize(
    ("error_type", "phase", "limit"),
    [
        (httpx.ConnectTimeout, "connect", 2.5),
        (httpx.ReadTimeout, "read", 7),
        (httpx.WriteTimeout, "write", 11),
        (httpx.PoolTimeout, "pool", 0.25),
        (httpx.TimeoutException, "request", None),
    ],
)
async def test_reports_actual_timeout_phase_and_request_override(
    monkeypatch, error_type, phase, limit
):
    error = error_type("")
    async with mock_gateway_client(monkeypatch, error) as client:
        with pytest.raises(error_type):
            await client.get(
                "status",
                timeout=httpx.Timeout(30, connect=2.5, read=7, write=11, pool=0.25),
            )
    diagnostic = find_payment_gateway_timeout(error)
    assert diagnostic.phase == phase
    assert diagnostic.timeout_seconds == limit
    assert diagnostic.method == "GET"


@pytest.mark.parametrize("timeout", [None, 0])
async def test_disabled_or_zero_timeout_is_not_reported_as_default(monkeypatch, timeout):
    error = httpx.ReadTimeout("")
    async with mock_gateway_client(monkeypatch, error) as client:
        with pytest.raises(httpx.ReadTimeout):
            await client.get("status", timeout=timeout)
    assert find_payment_gateway_timeout(error).timeout_seconds == timeout


async def test_finds_payment_timeout_in_wrapped_exception(monkeypatch):
    error = httpx.ReadTimeout("")
    async with mock_gateway_client(monkeypatch, error) as client:
        with pytest.raises(httpx.ReadTimeout):
            await client.get("status")
    wrapped = RuntimeError("Could not check payment")
    wrapped.__cause__ = error
    assert find_payment_gateway_timeout(wrapped).error_type == "ReadTimeout"
    assert wrapped.__cause__ is error


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectTimeout("No request context"),
        httpx.ReadTimeout("Other service", request=httpx.Request("GET", "https://panel.example")),
        httpx.ConnectError("Not a timeout"),
        RuntimeError("Not a network failure"),
    ],
)
def test_does_not_mislabel_unrelated_errors(error):
    assert find_payment_gateway_timeout(error) is None


def test_exception_context_cycle_does_not_hang():
    first, second = RuntimeError("first"), RuntimeError("second")
    first.__context__, second.__context__ = second, first
    assert find_payment_gateway_timeout(first) is None


@pytest.fixture(scope="module")
def translators():
    retort = RetortProvider().get_retort()
    return {
        locale: TranslatorRunnerImpl(
            [
                FluentTranslator(
                    locale=locale,
                    translator=FluentBundle.from_string(
                        locale=locale,
                        text="\n".join(
                            path.read_text("utf-8")
                            for path in sorted(Path(f"assets/translations/{locale}").glob("*.ftl"))
                        ),
                        use_isolating=False,
                    ),
                )
            ],
            retort,
        )
        for locale in ("ru", "en")
    }


@pytest.mark.parametrize("locale", ["ru", "en"])
@pytest.mark.parametrize(
    ("error_type", "ru_reason", "en_reason"),
    [
        (httpx.ConnectTimeout, "ожидания подключения", "connecting to the API"),
        (httpx.ReadTimeout, "ожидания ответа", "waiting for the API response"),
        (httpx.WriteTimeout, "передачи запроса", "sending the request"),
        (httpx.PoolTimeout, "свободного соединения", "available API connection"),
    ],
)
async def test_admin_notification_explains_timeout_and_keeps_traceback(
    monkeypatch, translators, locale, error_type, ru_reason, en_reason
):
    error = error_type("")
    async with mock_gateway_client(monkeypatch, error) as client:
        with pytest.raises(error_type):
            await client.post("v1/orders", timeout=12.5)
    event = ErrorEvent(telegram_id=123, name="<Alice & Bob>", exception=error)
    service = NotificationService.__new__(NotificationService)
    service.notify_system = AsyncMock()
    await service.on_error_event(event)
    payload = service.notify_system.await_args.args[0]
    assert payload.i18n_key == "event-error.payment-timeout"

    caption = translators[locale].get(payload.i18n_key, **payload.i18n_kwargs)
    visible = "".join(fromstring(f"<root>{caption}</root>").itertext())
    assert "Valutix" in visible
    assert (ru_reason if locale == "ru" else en_reason) in visible
    assert error_type.__name__ in visible
    assert "POST api.example.com" in visible
    assert "<Alice & Bob>" in visible
    assert ("12,5" if locale == "ru" else "12.5") in visible

    document = base64.b64decode(payload.media.value).decode("utf-8")
    assert document.startswith("=== PAYMENT GATEWAY TIMEOUT ===")
    assert "Payment gateway: VALUTIX" in document
    assert "Timeout limit: 12.5 s" in document
    assert "=== LOG CONTEXT (last 100 lines) ===" in document
    assert "=== EXCEPTION ===" in document
    assert error_type.__name__ in document
    assert "test_admin_notification_explains_timeout_and_keeps_traceback" in document
    assert event.exception is error


async def test_summary_excludes_credentials_query_tokens_and_customer_data(monkeypatch):
    error = httpx.ConnectTimeout("")
    async with mock_gateway_client(monkeypatch, error) as client:
        with pytest.raises(httpx.ConnectTimeout):
            await client.post(
                "https://merchant:private-password@api.example.com/private-path/token?api_key=private-api-key",
                json={"email": "customer@example.com"},
            )
    diagnostic = find_payment_gateway_timeout(error)
    summary = diagnostic.as_text()
    assert "POST api.example.com" in summary
    for secret in ("merchant", "private-password", "private-path", "private-api-key", "customer"):
        assert secret not in summary
        assert not any(secret in str(value) for value in diagnostic.as_i18n_kwargs().values())


async def test_ordinary_error_keeps_general_notification(translators):
    event = ErrorEvent(exception=ValueError("Ordinary error"))
    service = NotificationService.__new__(NotificationService)
    service.notify_system = AsyncMock()
    await service.on_error_event(event)
    payload = service.notify_system.await_args.args[0]
    assert payload.i18n_key == "event-error.general"
    assert "ValueError: Ordinary error" in translators["ru"].get(
        payload.i18n_key, **payload.i18n_kwargs
    )
    assert not base64.b64decode(payload.media.value).startswith(b"=== PAYMENT GATEWAY TIMEOUT ===")


async def test_real_valutix_payment_request_produces_readable_diagnostic(monkeypatch):
    error = httpx.ConnectTimeout("")
    # Install the mocked transport while retaining the shared client's hooks.
    async with mock_gateway_client(monkeypatch, error):
        gateway = ValutixGateway(
            PaymentGatewayDto(
                type=PaymentGatewayType.VALUTIX,
                currency=Currency.RUB,
                settings=ValutixGatewaySettingsDto(api_key=SecretStr("test-api-key")),
            ),
            SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username="test_bot"))),
            SimpleNamespace(get_webhook=lambda gateway_type: "https://bot.example/webhook"),
        )
        async with gateway._client:
            with pytest.raises(httpx.ConnectTimeout) as raised:
                await gateway.handle_create_payment(Decimal("100"), "Test payment")
    assert raised.value is error
    diagnostic = find_payment_gateway_timeout(error)
    assert diagnostic.gateway_type == PaymentGatewayType.VALUTIX
    assert diagnostic.host == "api.panel.valutix.kz"
    assert diagnostic.phase == "connect"
    assert error.request.extensions[PAYMENT_GATEWAY_EXTENSION] == PaymentGatewayType.VALUTIX.value


@pytest.mark.parametrize("is_timeout", [False, True])
async def test_telegram_stars_timeout_is_identified_without_mislabeling_other_network_errors(
    is_timeout,
):
    error = TelegramNetworkError(
        method=CreateInvoiceLink(
            title="Test", description="Test", payload="test", currency="XTR", prices=[]
        ),
        message="Request timeout error" if is_timeout else "Connection failed",
    )
    error.__cause__ = TimeoutError() if is_timeout else OSError("Connection failed")
    bot = SimpleNamespace(
        create_invoice_link=AsyncMock(side_effect=error),
        session=SimpleNamespace(
            timeout=60,
            api=SimpleNamespace(base="https://api.telegram.org/bot{token}/{method}"),
        ),
    )
    gateway = TelegramStarsGateway(
        PaymentGatewayDto(type=PaymentGatewayType.TELEGRAM_STARS, currency=Currency.XTR),
        bot,
        SimpleNamespace(),
    )
    with pytest.raises(TelegramNetworkError) as raised:
        await gateway.handle_create_payment(Decimal("100"), "Test payment")
    assert raised.value is error
    diagnostic = find_payment_gateway_timeout(error)
    if is_timeout:
        assert diagnostic.gateway_type == PaymentGatewayType.TELEGRAM_STARS
        assert diagnostic.phase == "request"
        assert diagnostic.host == "api.telegram.org"
        assert diagnostic.timeout_seconds == 60
    else:
        assert diagnostic is None
