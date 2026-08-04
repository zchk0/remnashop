from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import PlanDao, SubscriptionDao, UserDao
from src.application.common.policy import Permission
from src.application.dto import UserDto
from src.core.enums import BroadcastAudience

BROADCAST_REGISTRATION_EXCLUSION_DAYS = frozenset({7, 30, 90})


def validate_registration_exclusion(days: Optional[int]) -> None:
    if days is not None and days not in BROADCAST_REGISTRATION_EXCLUSION_DAYS:
        raise ValueError(f"Unsupported registration exclusion period: '{days}'")


@dataclass(frozen=True)
class GetBroadcastAudienceCountDto:
    audience: BroadcastAudience
    plan_id: Optional[int] = None
    excluded_telegram_ids: list[int] = field(default_factory=list)
    exclude_registered_within_days: Optional[int] = None


class HasAvailableBroadcastPlans(Interactor[None, bool]):
    required_permission = Permission.BROADCAST

    def __init__(self, plan_dao: PlanDao) -> None:
        self.plan_dao = plan_dao

    async def _execute(self, actor: UserDto, data: None) -> bool:
        return await self.plan_dao.count_non_trial() > 0


class GetBroadcastAudienceCount(Interactor[GetBroadcastAudienceCountDto, int]):
    required_permission = Permission.BROADCAST

    def __init__(
        self,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
    ) -> None:
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao

    async def _execute(self, actor: UserDto, data: GetBroadcastAudienceCountDto) -> int:
        audience = data.audience
        plan_id = data.plan_id
        excluded_telegram_ids = data.excluded_telegram_ids
        exclude_registered_within_days = data.exclude_registered_within_days
        validate_registration_exclusion(exclude_registered_within_days)

        if audience == BroadcastAudience.PLAN:
            if not plan_id:
                raise ValueError("PLAN audience requires a plan_id to count its size")
            count = await self.subscription_dao.count_active_by_plan(
                plan_id,
                excluded_telegram_ids,
                exclude_registered_within_days,
            )

        elif audience == BroadcastAudience.ALL:
            count = await self.user_dao.count_active_non_blocked(
                excluded_telegram_ids, exclude_registered_within_days
            )

        elif audience == BroadcastAudience.SUBSCRIBED:
            count = await self.user_dao.count_with_active_subscription(
                excluded_telegram_ids, exclude_registered_within_days
            )

        elif audience == BroadcastAudience.UNSUBSCRIBED:
            count = await self.user_dao.count_without_subscription(
                excluded_telegram_ids, exclude_registered_within_days
            )

        elif audience == BroadcastAudience.EXPIRED:
            count = await self.user_dao.count_with_expired_subscription(
                excluded_telegram_ids, exclude_registered_within_days
            )

        elif audience == BroadcastAudience.TRIAL:
            count = await self.user_dao.count_with_trial_subscription(
                excluded_telegram_ids, exclude_registered_within_days
            )

        else:
            logger.error(f"{actor.log} Received unknown broadcast audience '{audience}'")
            raise ValueError(f"Unknown broadcast audience '{audience}'")

        logger.info(f"{actor.log} Counted audience '{audience}' (plan_id='{plan_id}'): '{count}'")
        return count


@dataclass(frozen=True)
class GetBroadcastAudienceUsersDto:
    audience: BroadcastAudience
    plan_id: Optional[int] = None
    excluded_telegram_ids: list[int] = field(default_factory=list)
    exclude_registered_within_days: Optional[int] = None


class GetBroadcastAudienceUsers(Interactor[GetBroadcastAudienceUsersDto, list[UserDto]]):
    required_permission = Permission.BROADCAST

    def __init__(self, user_dao: UserDao) -> None:
        self.user_dao = user_dao

    async def _execute(self, actor: UserDto, data: GetBroadcastAudienceUsersDto) -> list[UserDto]:
        audience = data.audience
        plan_id = data.plan_id
        excluded_telegram_ids = data.excluded_telegram_ids
        exclude_registered_within_days = data.exclude_registered_within_days
        validate_registration_exclusion(exclude_registered_within_days)

        if audience == BroadcastAudience.PLAN:
            if plan_id is None:
                raise ValueError("plan_id is required for PLAN audience")
            users = await self.user_dao.get_active_by_plan(
                plan_id, excluded_telegram_ids, exclude_registered_within_days
            )
        elif audience == BroadcastAudience.ALL:
            users = await self.user_dao.get_active_non_blocked(
                excluded_telegram_ids, exclude_registered_within_days
            )
        elif audience == BroadcastAudience.SUBSCRIBED:
            users = await self.user_dao.get_with_active_subscription(
                excluded_telegram_ids, exclude_registered_within_days
            )
        elif audience == BroadcastAudience.UNSUBSCRIBED:
            users = await self.user_dao.get_without_subscription(
                excluded_telegram_ids, exclude_registered_within_days
            )
        elif audience == BroadcastAudience.EXPIRED:
            users = await self.user_dao.get_with_expired_subscription(
                excluded_telegram_ids, exclude_registered_within_days
            )
        elif audience == BroadcastAudience.TRIAL:
            users = await self.user_dao.get_with_trial_subscription(
                excluded_telegram_ids, exclude_registered_within_days
            )
        else:
            logger.error(f"{actor.log} Received unknown broadcast audience '{audience}'")
            raise ValueError(f"Unknown broadcast audience '{audience}'")

        logger.info(
            f"{actor.log} Retrieved '{len(users)}' users for audience '{audience}', "
            f"excluded Telegram IDs: '{len(excluded_telegram_ids)}', "
            f"registration exclusion days: '{exclude_registered_within_days}'"
        )
        return users
