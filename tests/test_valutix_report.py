from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from aiogram import Dispatcher
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from src.application.common.dao import TransactionDao
from src.application.common.uow import UnitOfWork
from src.application.dto import PaymentGatewayDto
from src.application.dto.payment_gateway import ValutixGatewaySettingsDto
from src.application.use_cases.gateways.queries.providers import GetPaymentGatewayInstance
from src.core.config import AppConfig
from src.core.enums import Currency, PaymentGatewayType
from src.infrastructure.database.dao.transaction import TransactionDaoImpl
from src.infrastructure.payment_gateways import base
from src.infrastructure.payment_gateways.valutix import ValutixGateway
from src.web.app import get_app
from src.web.endpoints import valutix_report

REPORT_PATH = "/api/v1/reports/valutix"
REPORT_HEADERS = {"X-Valutix-Report-Token": "test-report-token"}
PERIOD = {
    "from_date": "2026-10-31T17:00:00Z",
    "until_date": "2026-11-29T17:00:00Z",
}


@pytest.fixture
async def report(monkeypatch):
    monkeypatch.setattr(valutix_report, "PAGE_SIZE", 2)
    records = {}
    requests = []

    def respond(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url.host == "api.panel.valutix.kz"
        assert request.url.path.startswith("/v1/orders/")
        assert request.headers["X-Api-Token"] == "test-merchant-token"
        body = records[UUID(request.url.path.rsplit("/", 1)[-1])]
        if isinstance(body, int):
            return httpx.Response(body, json={"message": "private upstream message"})
        return httpx.Response(200, json=body)

    def make_client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(base, "AsyncClient", make_client)
    gateway = ValutixGateway(
        PaymentGatewayDto(
            type=PaymentGatewayType.VALUTIX,
            currency=Currency.RUB,
            settings=ValutixGatewaySettingsDto(api_key=SecretStr("test-merchant-token")),
        ),
        SimpleNamespace(),
        SimpleNamespace(),
    )
    config = SimpleNamespace(
        valutix_report_token=SecretStr(REPORT_HEADERS["X-Valutix-Report-Token"]),
        origins=[],
        tobevpn=SimpleNamespace(is_enabled=False),
        web_enabled=False,
        swagger_enabled=False,
        bot=SimpleNamespace(secret_token=SecretStr("test-webhook"), webhook_path="/telegram"),
    )

    async def list_ids(created_from, created_until, after_id, limit):
        assert created_from.isoformat() == "2026-10-31T16:00:00+00:00"
        assert created_until.isoformat() == "2026-11-29T18:00:00+00:00"
        rows = [(index, order_id) for index, order_id in enumerate(records, start=1)]
        return [row for row in rows if row[0] > after_id][:limit]

    dao = SimpleNamespace(list_valutix_order_ids=AsyncMock(side_effect=list_ids))
    deps = {
        AppConfig: config,
        GetPaymentGatewayInstance: SimpleNamespace(for_webhook=AsyncMock(return_value=gateway)),
        TransactionDao: dao,
        UnitOfWork: AsyncMock(),
    }

    class Container:
        async def get(self, dependency, component=""):
            return deps[dependency]

    app = get_app(config, Dispatcher())

    @app.middleware("http")
    async def supply_dependencies(request, call_next):
        request.state.dishka_container = Container()
        return await call_next(request)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://bot.example.org"
    ) as client:
        yield SimpleNamespace(client=client, records=records, requests=requests, dao=dao)
    await gateway._client.aclose()


def add_order(report, **changes):
    order_id = uuid4()
    report.records[order_id] = {
        "id": str(order_id),
        "status": "COMPLETED",
        "currency": "RUB",
        "isTest": False,
        "createdAt": "2026-10-31T17:00:00.000Z",
        "received": "123.45",
        **changes,
    }


@pytest.mark.parametrize("headers", [{}, {"X-Valutix-Report-Token": "wrong-token"}])
async def test_report_rejects_invalid_token_before_reading_orders(report, headers):
    response = await report.client.get(REPORT_PATH, params=PERIOD, headers=headers)
    assert response.status_code == 401
    report.dao.list_valutix_order_ids.assert_not_called()
    assert report.requests == []


async def test_report_pages_use_provider_amount_status_currency_and_creation_date(report):
    add_order(report)
    add_order(report, isTest=True)
    add_order(report, received="0.55", settlementCurrency="RUB")
    add_order(report, status="REFUND")
    add_order(report, currency="USD")
    add_order(report, createdAt=PERIOD["until_date"])

    expected = [("123.45", 1, 2), ("0.55", 1, 4), ("0", 0, None)]
    cursor = 0
    for amount, count, next_cursor in expected:
        response = await report.client.get(
            REPORT_PATH, params={**PERIOD, "cursor": cursor}, headers=REPORT_HEADERS
        )
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "private, no-store"
        assert response.json() == {
            "total_received_rub": amount,
            "completed_payments": count,
            "next_cursor": next_cursor,
        }
        cursor = next_cursor
    assert len(report.requests) == 6


@pytest.mark.parametrize("failure", [403, {"received": None}, {"settlementCurrency": "USDT"}])
async def test_failed_lookup_returns_error_without_partial_total(report, failure):
    add_order(report)
    if isinstance(failure, int):
        report.records[uuid4()] = failure
    else:
        add_order(report, **failure)

    response = await report.client.get(REPORT_PATH, params=PERIOD, headers=REPORT_HEADERS)
    assert response.status_code == 502
    assert "total_received_rub" not in response.json()
    assert "private upstream message" not in response.text


async def test_dao_pages_only_paid_valutix_orders_with_local_ids_in_range():
    from_date = datetime(2026, 11, 1, tzinfo=UTC)
    until_date = datetime(2026, 11, 30, tzinfo=UTC)
    order_ids = [uuid4() for _ in range(6)]
    rows = [
        (1, "VALUTIX", "2026-11-20", '{"final_amount": "100"}'),
        (2, "VALUTIX", "2026-11-21", '{"final_amount": "0"}'),
        (3, "FLIPPAY", "2026-11-22", '{"final_amount": 100}'),
        (4, "VALUTIX", "2026-11-23", '{"final_amount": "50"}'),
        (5, "VALUTIX", "2026-10-30", '{"final_amount": "100"}'),
        (6, "VALUTIX", "2026-11-24", '{"final_amount": 100}'),
    ]
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE transactions "
                "(id INTEGER PRIMARY KEY, payment_id CHAR(32), gateway_type TEXT, "
                "created_at TEXT, pricing JSON)"
            )
        )
        connection.execute(
            text("INSERT INTO transactions VALUES (:id, :payment_id, :gateway, :date, :pricing)"),
            [
                {
                    "id": index,
                    "payment_id": order_ids[index - 1].hex,
                    "gateway": gateway,
                    "date": created_at,
                    "pricing": pricing,
                }
                for index, gateway, created_at, pricing in rows
            ],
        )
        dao = object.__new__(TransactionDaoImpl)
        dao.session = SimpleNamespace(execute=AsyncMock(side_effect=connection.execute))
        assert await dao.list_valutix_order_ids(from_date, until_date, 0, 2) == [
            (1, order_ids[0]),
            (4, order_ids[3]),
        ]
        assert await dao.list_valutix_order_ids(from_date, until_date, 4, 2) == [(6, order_ids[5])]
    engine.dispose()
