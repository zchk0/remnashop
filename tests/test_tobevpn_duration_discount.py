from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.common import BotService
from src.application.common.dao import PaymentGatewayDao, SubscriptionDao, UserDao
from src.application.dto import (
    PaymentGatewayDto,
    PlanDto,
    PlanDurationDto,
    PlanPriceDto,
    TelegramUserDto,
)
from src.application.services import PricingService
from src.application.use_cases.plan.queries.match import MatchPlan
from src.application.use_cases.user.queries.plans import GetAvailablePlans
from src.core.enums import Currency, PaymentGatewayType
from src.web.endpoints.devices import DeviceAuthContext, get_device_auth_context, router


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("personal_discount", [0, 20, 100])
def test_purchase_api_exposes_duration_discount_per_currency(
    enabled: bool, personal_discount: int
) -> None:
    def duration(days: int, rub: str, usd: str) -> PlanDurationDto:
        return PlanDurationDto(
            days=days,
            prices=[
                PlanPriceDto(currency=Currency.RUB, price=Decimal(rub)),
                PlanPriceDto(currency=Currency.USD, price=Decimal(usd)),
            ],
        )

    plan = PlanDto(
        id=10,
        name="Plan",
        show_duration_discount=enabled,
        durations=[
            duration(30, "450", "5"),
            duration(90, "1199", "12"),
            duration(365, "4199", "50"),
            duration(0, "10000", "100"),
            duration(60, "0", "0"),
        ],
    )
    user = TelegramUserDto(id=1, telegram_id=123, name="User", personal_discount=personal_discount)
    pricing = PricingService()
    deps = {
        UserDao: SimpleNamespace(get_by_telegram_id=AsyncMock(return_value=user)),
        SubscriptionDao: SimpleNamespace(get_current=AsyncMock(return_value=None)),
        PaymentGatewayDao: SimpleNamespace(
            get_active=AsyncMock(
                return_value=[
                    PaymentGatewayDto(type=PaymentGatewayType.PLATEGA, currency=Currency.RUB),
                    PaymentGatewayDto(type=PaymentGatewayType.CRYPTOPAY, currency=Currency.USD),
                ]
            )
        ),
        GetAvailablePlans: SimpleNamespace(system=AsyncMock(return_value=[plan])),
        MatchPlan: SimpleNamespace(system=AsyncMock(return_value=None)),
        BotService: SimpleNamespace(get_purchase_url=AsyncMock(return_value="https://t.me/test")),
        PricingService: pricing,
    }

    class FakeContainer:
        async def get(self, dependency, component=""):
            return deps[dependency]

    app = FastAPI()

    @app.middleware("http")
    async def inject_container(request, call_next):
        request.state.dishka_container = FakeContainer()
        return await call_next(request)

    app.dependency_overrides[get_device_auth_context] = lambda: DeviceAuthContext(
        telegram_id=123, short_uuid="short"
    )
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/api/purchase/plans")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["effective_discount_percent"] == personal_discount
    offers = data["plans"][0]["durations"]
    assert len(offers) == len(plan.durations)
    expected_discounts = {30: (0, 0), 90: (11, 20), 365: (23, 17), 0: (0, 0), 60: (0, 0)}
    for offer, selected in zip(offers, plan.durations):
        assert offer["days"] == selected.days
        assert offer["bot_start_param"].endswith(f"10_{selected.days}")
        for price, method, original, discount in zip(
            offer["prices"],
            offer["payment_methods"],
            selected.prices,
            expected_discounts[selected.days],
        ):
            expected = pricing.calculate(user, original.price, original.currency)
            assert price["currency"] == method["currency"] == original.currency.value
            assert Decimal(price["amount"]) == original.price
            assert Decimal(method["original_amount"]) == expected.original_amount
            assert Decimal(method["final_amount"]) == expected.final_amount
            assert method["discount_percent"] == expected.discount_percent
            assert price["duration_discount_percent"] == (discount if enabled else 0)
            assert method["duration_discount_percent"] == (
                discount if enabled and expected.final_amount > 0 else 0
            )
