from datetime import UTC, datetime, timedelta, timezone

import pytest
from remnapy.enums import TrafficLimitStrategy

from src.core.utils.time import get_next_traffic_reset_at, get_traffic_reset_delta


@pytest.mark.parametrize(
    ("strategy", "now", "expected"),
    [
        ("DAY", "2026-10-07T00:04:59", "2026-10-07T00:05:00"),
        ("DAY", "2026-10-07T00:05:00", "2026-10-08T00:05:00"),
        ("DAY", "2026-12-31T23:59:59", "2027-01-01T00:05:00"),
        ("WEEK", "2026-10-05T00:14:59", "2026-10-05T00:15:00"),
        ("WEEK", "2026-10-05T00:15:00", "2026-10-12T00:15:00"),
        ("WEEK", "2026-10-11T12:00:00", "2026-10-12T00:15:00"),
        ("MONTH", "2026-10-01T00:19:59", "2026-10-01T00:20:00"),
        ("MONTH", "2026-10-01T00:20:00", "2026-11-01T00:20:00"),
        ("MONTH", "2026-12-31T12:00:00", "2027-01-01T00:20:00"),
    ],
)
def test_calendar_reset_boundaries(
    monkeypatch: pytest.MonkeyPatch, strategy: str, now: str, expected: str
) -> None:
    current = datetime.fromisoformat(now).replace(tzinfo=UTC)
    monkeypatch.setattr("src.core.utils.time.datetime_now", lambda: current)
    expected_at = datetime.fromisoformat(expected).replace(tzinfo=UTC)

    assert get_next_traffic_reset_at(TrafficLimitStrategy(strategy)) == expected_at
    assert get_traffic_reset_delta(TrafficLimitStrategy(strategy)) == expected_at - current


@pytest.mark.parametrize(
    ("created", "now", "expected"),
    [
        ("2026-01-31T12:00:00", "2026-02-01T12:00:00", "2026-02-28T00:10:00"),
        ("2024-01-31T12:00:00", "2024-02-01T12:00:00", "2024-02-29T00:10:00"),
        ("2026-01-31T12:00:00", "2026-02-28T00:10:00", "2026-03-31T00:10:00"),
        ("2026-01-30T12:00:00", "2026-02-01T12:00:00", "2026-02-28T00:10:00"),
        ("2026-01-29T12:00:00", "2026-02-01T12:00:00", "2026-02-28T00:10:00"),
        ("2026-10-07T12:00:00", "2026-10-08T12:00:00", "2026-11-07T00:10:00"),
        ("2026-01-07T12:00:00", "2026-10-07T00:09:59", "2026-10-07T00:10:00"),
        ("2026-01-07T12:00:00", "2026-10-07T00:10:00", "2026-11-07T00:10:00"),
    ],
)
def test_rolling_reset_uses_creation_day_and_short_months(
    monkeypatch: pytest.MonkeyPatch, created: str, now: str, expected: str
) -> None:
    monkeypatch.setattr(
        "src.core.utils.time.datetime_now", lambda: datetime.fromisoformat(now).replace(tzinfo=UTC)
    )

    assert get_next_traffic_reset_at(
        TrafficLimitStrategy.MONTH_ROLLING,
        datetime.fromisoformat(created).replace(tzinfo=UTC),
    ) == datetime.fromisoformat(expected).replace(tzinfo=UTC)


@pytest.mark.parametrize(
    ("strategy", "expected"),
    [
        (TrafficLimitStrategy.DAY, datetime(2026, 10, 8, 0, 5, tzinfo=UTC)),
        (TrafficLimitStrategy.WEEK, datetime(2026, 10, 12, 0, 15, tzinfo=UTC)),
        (TrafficLimitStrategy.MONTH, datetime(2026, 11, 1, 0, 20, tzinfo=UTC)),
        (TrafficLimitStrategy.MONTH_ROLLING, datetime(2026, 10, 15, 0, 10, tzinfo=UTC)),
    ],
)
def test_manual_reset_does_not_move_schedule(
    monkeypatch: pytest.MonkeyPatch, strategy: TrafficLimitStrategy, expected: datetime
) -> None:
    monkeypatch.setattr(
        "src.core.utils.time.datetime_now", lambda: datetime(2026, 10, 7, 12, tzinfo=UTC)
    )

    assert (
        get_next_traffic_reset_at(
            strategy,
            datetime(2026, 1, 15, tzinfo=UTC),
            last_traffic_reset_at=datetime(2026, 10, 7, 11, tzinfo=UTC),
        )
        == expected
    )


def test_rolling_creation_date_is_normalized_to_panel_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.core.utils.time.datetime_now", lambda: datetime(2026, 10, 7, 12, tzinfo=UTC)
    )
    created = datetime(2026, 1, 16, 1, tzinfo=timezone(timedelta(hours=7)))

    assert get_next_traffic_reset_at(TrafficLimitStrategy.MONTH_ROLLING, created) == datetime(
        2026, 10, 15, 0, 10, tzinfo=UTC
    )


def test_no_reset_has_no_next_date() -> None:
    assert get_next_traffic_reset_at(TrafficLimitStrategy.NO_RESET) is None
    assert get_traffic_reset_delta(TrafficLimitStrategy.NO_RESET) == timedelta(0)


def test_rolling_reset_requires_panel_creation_date() -> None:
    with pytest.raises(ValueError, match="subscription_created_at is required"):
        get_next_traffic_reset_at(TrafficLimitStrategy.MONTH_ROLLING)
