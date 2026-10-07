from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fluent_compiler.bundle import FluentBundle
from fluentogram.translator import FluentTranslator
from remnapy.enums import TrafficLimitStrategy

from src.application.use_cases.misc.queries.menu import GetMenuData
from src.core.enums import Role, SubscriptionStatus


def _menu_data(
    strategy: TrafficLimitStrategy = TrafficLimitStrategy.MONTH_ROLLING,
    panel_user: SimpleNamespace | None = None,
) -> tuple[GetMenuData, SimpleNamespace, AsyncMock]:
    subscription = SimpleNamespace(
        user_remna_id="panel-user-id",
        created_at=datetime(2026, 10, 3, tzinfo=UTC),
        has_traffic_limit=True,
        current_status=SubscriptionStatus.ACTIVE,
        traffic_limit_strategy=strategy,
    )
    fetch_user = AsyncMock(return_value=panel_user)
    service = GetMenuData.__new__(GetMenuData)
    service.remnawave = SimpleNamespace(get_user_by_uuid=fetch_user)
    service.subscription_dao = SimpleNamespace(get_current=AsyncMock(return_value=subscription))
    service.settings_dao = SimpleNamespace(
        get=AsyncMock(
            return_value=SimpleNamespace(
                referral=SimpleNamespace(enable=False), menu=SimpleNamespace(buttons=[])
            )
        )
    )
    service.bot_service = SimpleNamespace(get_referral_url=AsyncMock(return_value="referral-url"))
    return service, subscription, fetch_user


async def test_menu_uses_panel_creation_date_instead_of_shop_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.core.utils.time.datetime_now", lambda: datetime(2026, 10, 7, 12, tzinfo=UTC)
    )
    service, subscription, fetch_user = _menu_data(
        panel_user=SimpleNamespace(
            traffic_limit_bytes=100,
            traffic_limit_strategy=TrafficLimitStrategy.MONTH_ROLLING,
            created_at=datetime(2026, 1, 15, tzinfo=UTC),
            last_traffic_reset_at=datetime(2026, 10, 3, 12, tzinfo=UTC),
        )
    )
    actor = SimpleNamespace(id=1, is_trial_available=False, referral_code="ref", role=Role.USER)

    result = await service._execute(actor, None)

    assert result.traffic_reset_at == datetime(2026, 10, 15, 0, 10, tzinfo=UTC)
    assert result.current_subscription is subscription
    fetch_user.assert_awaited_once_with("panel-user-id")


@pytest.mark.parametrize(
    ("strategy", "expected"),
    [
        (TrafficLimitStrategy.MONTH_ROLLING, None),
        (TrafficLimitStrategy.MONTH, datetime(2026, 11, 1, 0, 20, tzinfo=UTC)),
    ],
)
async def test_panel_outage_keeps_menu_available_without_guessing_rolling_anchor(
    monkeypatch: pytest.MonkeyPatch,
    strategy: TrafficLimitStrategy,
    expected: datetime | None,
) -> None:
    monkeypatch.setattr(
        "src.core.utils.time.datetime_now", lambda: datetime(2026, 10, 7, 12, tzinfo=UTC)
    )
    service, _, fetch_user = _menu_data(strategy)
    fetch_user.side_effect = TimeoutError("Panel unavailable")
    actor = SimpleNamespace(id=1, is_trial_available=False, referral_code="ref", role=Role.USER)

    result = await service._execute(actor, None)

    assert result.current_subscription is not None
    assert result.traffic_reset_at == expected


@pytest.mark.parametrize(
    ("strategy", "status", "has_traffic_limit"),
    [
        (TrafficLimitStrategy.NO_RESET, SubscriptionStatus.ACTIVE, True),
        (TrafficLimitStrategy.MONTH, SubscriptionStatus.EXPIRED, True),
        (TrafficLimitStrategy.MONTH, SubscriptionStatus.DISABLED, True),
        (TrafficLimitStrategy.MONTH, SubscriptionStatus.ACTIVE, False),
    ],
)
async def test_no_date_or_panel_request_when_reset_is_not_applicable(
    strategy: TrafficLimitStrategy, status: SubscriptionStatus, has_traffic_limit: bool
) -> None:
    service, subscription, fetch_user = _menu_data(strategy)
    subscription.current_status = status
    subscription.has_traffic_limit = has_traffic_limit

    assert await service.get_traffic_reset_at(subscription) is None
    fetch_user.assert_not_awaited()


@pytest.mark.parametrize("status", ["ACTIVE", "LIMITED"])
@pytest.mark.parametrize("next_reset_at", [0, "15.10.2026"])
def test_menu_displays_next_reset_date_when_available(
    status: str, next_reset_at: int | str
) -> None:
    texts = [
        path.read_text("utf-8") for path in sorted(Path("assets/translations/ru").glob("*.ftl"))
    ]
    translator = FluentTranslator(
        locale="ru",
        translator=FluentBundle.from_string(
            locale="ru", text="\n".join(texts), use_isolating=False
        ),
    )

    rendered = translator.get(
        "msg-main-menu",
        telegram_id=123,
        email=0,
        name="User",
        show_personal_discount=0,
        show_purchase_discount=0,
        status=status,
        is_trial=0,
        traffic_strategy="MONTH_ROLLING",
        traffic_limit="100 ГБ",
        device_limit="3",
        expire_time="20 дней",
        reset_time="8 дней",
        has_subscription_url=1,
        subscription_url="https://example.com/sub/short",
        next_reset_at=next_reset_at,
    )

    if next_reset_at:
        assert "Следующий сброс трафика" in rendered
        assert next_reset_at in rendered
        reset_index = rendered.index("Следующий сброс трафика")
        block_start = rendered.rfind("<blockquote>", 0, reset_index)
        block_end = rendered.index("</blockquote>", block_start)
        assert block_start < reset_index < block_end
        if status == "ACTIVE":
            assert rendered.index("Лимит трафика") < reset_index < rendered.index("Лимит устройств")
        assert rendered.count("Следующий сброс трафика") == 1
    else:
        assert "Следующий сброс трафика" not in rendered
