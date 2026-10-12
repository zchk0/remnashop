from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from adaptix import Retort
from fluent_compiler.bundle import FluentBundle
from fluentogram.translator import FluentTranslator

from src.application.dto import PlanDto, PlanDurationDto, PlanPriceDto, TelegramUserDto
from src.application.services import PricingService
from src.core.enums import Currency
from src.telegram.routers.subscription.getters import duration_getter


def _duration(days: int, price: str, currency: Currency = Currency.RUB) -> PlanDurationDto:
    return PlanDurationDto(
        days=days, prices=[PlanPriceDto(currency=currency, price=Decimal(price))]
    )


@pytest.fixture(scope="module")
def translator() -> FluentTranslator:
    texts = [
        path.read_text("utf-8") for path in sorted(Path("assets/translations/ru").glob("*.ftl"))
    ]
    return FluentTranslator(
        locale="ru",
        translator=FluentBundle.from_string(
            locale="ru", text="\n".join(texts), use_isolating=False
        ),
    )


@pytest.mark.parametrize(
    ("days", "price", "expected"),
    [(30, "450", 0), (90, "1199", 11), (365, "4199", 23), (45, "600", 11)],
)
def test_discount_compares_prices_per_day(days: int, price: str, expected: int) -> None:
    selected = _duration(days, price)
    # Display order and unlimited options must not determine the baseline.
    plan = PlanDto(
        show_duration_discount=True,
        durations=[_duration(0, "1"), _duration(730, "5000"), _duration(30, "450")],
    )
    assert PricingService().get_duration_discount(plan, selected, Currency.RUB) == expected


@pytest.mark.parametrize(
    ("enabled", "base_days", "base_price", "days", "price"),
    [
        (False, 30, "450", 90, "1199"),
        (True, 30, "0", 90, "1199"),
        (True, 30, "450", 0, "1199"),
        (True, 30, "450", 90, "0"),
        (True, 30, "450", 90, "1350"),
        (True, 30, "450", 90, "1500"),
        (True, 30, "450", 90, "1349"),
        (True, 0, "450", 90, "1199"),
    ],
)
def test_discount_is_hidden_when_inapplicable(
    enabled: bool, base_days: int, base_price: str, days: int, price: str
) -> None:
    selected = _duration(days, price)
    plan = PlanDto(
        show_duration_discount=enabled,
        durations=[_duration(base_days, base_price), selected],
    )
    assert PricingService().get_duration_discount(plan, selected, Currency.RUB) == 0


def test_discount_uses_matching_currency_without_changing_baseline() -> None:
    shortest = _duration(30, "450")
    shortest.prices.append(PlanPriceDto(currency=Currency.USD, price=Decimal("5")))
    selected = _duration(90, "1199")
    selected.prices.append(PlanPriceDto(currency=Currency.USD, price=Decimal("12")))
    plan = PlanDto(show_duration_discount=True, durations=[shortest, selected])
    service = PricingService()
    assert service.get_duration_discount(plan, selected, Currency.USD) == 20
    assert service.get_duration_discount(plan, selected, Currency.RUB) == 11

    shortest.prices = [price for price in shortest.prices if price.currency != Currency.USD]
    assert service.get_duration_discount(plan, selected, Currency.USD) == 0


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize(
    ("personal_discount", "purchase_discount", "expected_discounts"),
    [
        (0, 0, (0, 11)),
        (20, 0, (20, 28)),
        (0, 20, (20, 28)),
        (30, 20, (30, 37)),
        (20, 30, (30, 37)),
        (0, 100, (0, 0)),
    ],
)
async def test_duration_buttons_keep_purchase_prices_and_hide_zero_discount(
    translator: FluentTranslator,
    enabled: bool,
    personal_discount: int,
    purchase_discount: int,
    expected_discounts: tuple[int, int],
) -> None:
    retort = Retort()
    plan = PlanDto(
        name="plan-default-name",
        show_duration_discount=enabled,
        durations=[_duration(30, "450"), _duration(90, "1199")],
    )
    manager = SimpleNamespace(dialog_data={PlanDto.__name__: retort.dump(plan)})
    user = TelegramUserDto(
        id=1,
        telegram_id=1,
        name="Test",
        personal_discount=personal_discount,
        purchase_discount=purchase_discount,
    )
    settings_dao = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(default_currency=Currency.RUB))
    )
    service = PricingService()
    data = await duration_getter.__dishka_orig_func__(
        dialog_manager=manager,
        user=user,
        retort=retort,
        i18n=translator,
        settings_dao=settings_dao,
        pricing_service=service,
    )
    for item, duration, expected_discount in zip(
        data["durations"], plan.durations, expected_discounts
    ):
        assert (
            item["final_amount"]
            == service.calculate(user, duration.get_price(Currency.RUB), Currency.RUB).final_amount
        )
        rendered = translator.get("btn-subscription.duration", **item)
        expected_discount = expected_discount if enabled else 0
        assert item["duration_discount_percent"] == expected_discount
        if expected_discount:
            assert f"(-{expected_discount}%)" in rendered
        else:
            assert "(-" not in rendered
        assert "(-0%)" not in rendered


def test_flag_survives_serialization_and_old_plans_default_to_disabled() -> None:
    retort = Retort()
    raw = retort.dump(PlanDto(show_duration_discount=True))
    assert retort.load(raw, PlanDto).show_duration_discount is True
    raw.pop("show_duration_discount")
    assert retort.load(raw, PlanDto).show_duration_discount is False


@pytest.mark.parametrize("enabled", [0, 1])
def test_toggle_label_shows_current_state(translator: FluentTranslator, enabled: int) -> None:
    rendered = translator.get("btn-plans.duration-discount-toggle", show_duration_discount=enabled)
    assert "Показывать скидку за срок" in rendered
    assert ("🔘" in rendered) == bool(enabled)
