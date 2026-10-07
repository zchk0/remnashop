from datetime import datetime
from typing import Optional

from loguru import logger
from remnapy.enums import TrafficLimitStrategy

from src.application.common import Remnawave
from src.application.dto import SubscriptionDto
from src.core.enums import SubscriptionStatus
from src.core.types import RemnaUserDto
from src.core.utils.time import get_next_traffic_reset_at


def get_panel_traffic_reset_at(user: RemnaUserDto) -> Optional[datetime]:
    if not user.traffic_limit_bytes:
        return None
    return get_next_traffic_reset_at(
        TrafficLimitStrategy(user.traffic_limit_strategy),
        user.created_at,
        last_traffic_reset_at=user.last_traffic_reset_at,
    )


async def get_subscription_traffic_reset_at(
    subscription: SubscriptionDto,
    remnawave: Remnawave,
) -> Optional[datetime]:
    if (
        not subscription.has_traffic_limit
        or subscription.current_status
        not in (SubscriptionStatus.ACTIVE, SubscriptionStatus.LIMITED)
        or subscription.traffic_limit_strategy == TrafficLimitStrategy.NO_RESET
    ):
        return None

    try:
        user = await remnawave.get_user_by_uuid(subscription.user_remna_id)
        if user is not None:
            return get_panel_traffic_reset_at(user)
    except Exception as e:
        logger.warning(
            f"Could not fetch traffic reset data for '{subscription.user_remna_id}': {e}"
        )

    # Rolling resets need the panel user's creation date, not a shop subscription's date.
    if subscription.traffic_limit_strategy == TrafficLimitStrategy.MONTH_ROLLING:
        return None
    return get_next_traffic_reset_at(subscription.traffic_limit_strategy)
