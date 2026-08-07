from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.events.user import SubscriptionExpiredAgoEvent, SubscriptionExpiresEvent
from src.application.services.remnawave import RemnaWebhookService
from src.core.enums import UserNotificationType
from src.core.utils.remnawave import extract_expiration_hours


def _service() -> tuple[RemnaWebhookService, AsyncMock]:
    user = SimpleNamespace(id=1)
    expire_at = datetime(2026, 8, 10, tzinfo=UTC)
    subscription = SimpleNamespace(expire_at=expire_at, is_trial=False)
    event_bus = AsyncMock()

    service = RemnaWebhookService.__new__(RemnaWebhookService)
    service.user_dao = SimpleNamespace(get_by_remna_uuid=AsyncMock(return_value=user))
    service.subscription_dao = SimpleNamespace(get_current=AsyncMock(return_value=subscription))
    service.event_bus = event_bus

    return service, event_bus.publish


@pytest.mark.parametrize(
    ("hours", "day", "notification_type"),
    [
        (-72, 3, UserNotificationType.EXPIRES_IN_3_DAYS),
        (-48, 2, UserNotificationType.EXPIRES_IN_2_DAYS),
        (-24, 1, UserNotificationType.EXPIRES_IN_1_DAY),
    ],
)
async def test_remnawave_28_upcoming_expiration_event(
    hours: int,
    day: int,
    notification_type: UserNotificationType,
) -> None:
    service, publish = _service()
    remna_user = SimpleNamespace(
        uuid="remna-uuid",
        telegram_id=123,
        expire_at=datetime(2026, 8, 10, tzinfo=UTC),
    )

    await service.handle_user_event("user.expiration", remna_user, expiration_hours=hours)

    event = publish.await_args.args[0]
    assert isinstance(event, SubscriptionExpiresEvent)
    assert event.day == day
    assert event.notification_type == notification_type


async def test_remnawave_28_expired_one_day_ago_event() -> None:
    service, publish = _service()
    remna_user = SimpleNamespace(
        uuid="remna-uuid",
        telegram_id=123,
        expire_at=datetime(2026, 8, 10, tzinfo=UTC),
    )

    await service.handle_user_event("user.expiration", remna_user, expiration_hours=24)

    event = publish.await_args.args[0]
    assert isinstance(event, SubscriptionExpiredAgoEvent)
    assert event.day == 1
    assert event.notification_type == UserNotificationType.EXPIRED_1_DAY_AGO


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"meta": {"expiration": -72}}, -72),
        ({"meta": {"expiration": 24.0}}, 24),
        ({"meta": None}, None),
        ({"meta": {"expiration": -24.5}}, None),
    ],
)
def test_extract_expiration_hours(payload: dict, expected: int | None) -> None:
    assert extract_expiration_hours(payload) == expected
