import time
from calendar import monthrange
from datetime import datetime, timedelta
from typing import Optional

from remnapy.enums.users import TrafficLimitStrategy

from src.core.constants import TIMEZONE

START_TIME: int = int(time.time())


def datetime_now() -> datetime:
    return datetime.now(tz=TIMEZONE)


def get_uptime() -> int:
    uptime_seconds = int(time.time() - START_TIME)
    return uptime_seconds


def get_next_traffic_reset_at(
    strategy: TrafficLimitStrategy,
    subscription_created_at: Optional[datetime] = None,
    *,
    last_traffic_reset_at: Optional[datetime] = None,
) -> Optional[datetime]:
    """Return the next scheduled reset for a Remnawave 2.8.1 panel running in UTC.

    A manual reset does not move the calendar schedule or the rolling creation-day anchor.
    """
    now = datetime_now()
    if last_traffic_reset_at is not None:
        now = max(now, last_traffic_reset_at.astimezone(TIMEZONE))

    if strategy == TrafficLimitStrategy.NO_RESET:
        return None

    if strategy == TrafficLimitStrategy.DAY:
        reset_at = now.replace(hour=0, minute=5, second=0, microsecond=0)
        return reset_at if reset_at > now else reset_at + timedelta(days=1)

    if strategy == TrafficLimitStrategy.WEEK:
        reset_at = now.replace(hour=0, minute=15, second=0, microsecond=0)
        reset_at += timedelta(days=(7 - now.weekday()) % 7)
        return reset_at if reset_at > now else reset_at + timedelta(days=7)

    if strategy == TrafficLimitStrategy.MONTH:
        reset_at = now.replace(day=1, hour=0, minute=20, second=0, microsecond=0)
        if reset_at <= now:
            reset_at = (reset_at + timedelta(days=32)).replace(day=1)
        return reset_at

    if strategy == TrafficLimitStrategy.MONTH_ROLLING:
        if subscription_created_at is None:
            raise ValueError("subscription_created_at is required for MONTH_ROLLING strategy")
        return _get_monthly_rolling_reset_at(now, subscription_created_at.astimezone(TIMEZONE))

    raise ValueError("Unsupported strategy")


def _get_monthly_rolling_reset_at(now: datetime, created_at: datetime) -> datetime:
    def reset_in_month(month: datetime) -> datetime:
        day = min(created_at.day, monthrange(month.year, month.month)[1])
        return month.replace(day=day, hour=0, minute=10, second=0, microsecond=0)

    month_start = now.replace(day=1)
    reset_at = reset_in_month(month_start)
    if reset_at <= now:
        reset_at = reset_in_month((month_start + timedelta(days=32)).replace(day=1))
    first_month = (created_at.replace(day=1) + timedelta(days=32)).replace(day=1)
    return max(reset_at, reset_in_month(first_month))


def get_traffic_reset_delta(
    strategy: TrafficLimitStrategy,
    subscription_created_at: Optional[datetime] = None,
    *,
    last_traffic_reset_at: Optional[datetime] = None,
) -> timedelta:
    reset_at = get_next_traffic_reset_at(
        strategy,
        subscription_created_at,
        last_traffic_reset_at=last_traffic_reset_at,
    )
    return reset_at - datetime_now() if reset_at is not None else timedelta(0)
