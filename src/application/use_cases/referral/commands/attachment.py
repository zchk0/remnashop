from dataclasses import dataclass
from typing import Optional

from loguru import logger

from src.application.common import EventPublisher, Interactor
from src.application.common.dao import ReferralDao, SettingsDao, UserDao
from src.application.common.uow import UnitOfWork
from src.application.dto import ReferralDto, ReferralRewardDto, UserDto
from src.application.events import ReferralAttachedEvent
from src.core.enums import ReferralLevel

from .rewards import GiveReferrerReward, GiveReferrerRewardDto


@dataclass(frozen=True)
class AttachReferralDto:
    user_id: int
    referral_code: str


class AttachReferral(Interactor[AttachReferralDto, Optional[UserDto]]):
    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        settings_dao: SettingsDao,
        user_dao: UserDao,
        referral_dao: ReferralDao,
        event_publisher: EventPublisher,
        give_referrer_reward: GiveReferrerReward,
    ) -> None:
        self.uow = uow
        self.settings_dao = settings_dao
        self.user_dao = user_dao
        self.referral_dao = referral_dao
        self.event_publisher = event_publisher
        self.give_referrer_reward = give_referrer_reward

    async def _execute(self, actor: UserDto, data: AttachReferralDto) -> Optional[UserDto]:
        settings = await self.settings_dao.get()
        if not settings.referral.enable:
            logger.info("Referral skipped: referral system is disabled")
            return None

        referrer = await self.user_dao.get_by_referral_code(data.referral_code)

        if not referrer:
            logger.info(f"Referral skipped: referrer not found for code '{data.referral_code}'")
            return None

        if referrer.id == data.user_id:
            logger.warning(
                f"Referral skipped: self-referral by user '{data.user_id}' "
                f"with code '{data.referral_code}'"
            )
            return None

        existing, parent = await self.referral_dao.get_referral_chain(data.user_id)
        if existing:
            logger.info(f"Referral skipped: user '{data.user_id}' already referred")
            return None

        level = self._define_referral_level(parent.level if parent else None)

        logger.info(
            f"Referral detected '{referrer.remna_name}' -> "
            f"'{data.user_id}' with level '{level.name}'"
        )

        invitation_reward = None
        async with self.uow:
            referred = await self.user_dao.get_by_id(data.user_id)
            if not referred:
                logger.warning(f"Referral skipped: referred user not found '{data.user_id}'")
                return None

            referral = await self.referral_dao.create_referral(
                ReferralDto(
                    level=level,
                    referrer=referrer,
                    referred=referred,
                )
            )
            if settings.referral.accrual_strategy.rewards_invitation:
                invitation_reward = await self.referral_dao.create_reward(
                    reward=ReferralRewardDto(
                        user_id=referrer.id,
                        type=settings.referral.reward.type,
                        amount=settings.referral.invitation_reward,
                    ),
                    referral_id=referral.id,
                )
            await self.uow.commit()

        if invitation_reward:
            try:
                await self.give_referrer_reward.system(
                    GiveReferrerRewardDto(
                        user_id=referrer.id,
                        reward=invitation_reward,
                        referred_name=referred.name,
                        is_invitation=True,
                    )
                )
            except Exception:
                logger.exception(
                    f"Could not issue invitation reward '{invitation_reward.id}' "
                    f"to user '{referrer.id}' — referral is saved"
                )

        try:
            await self.event_publisher.publish(
                ReferralAttachedEvent(user=referrer, name=referred.name)
            )
        except Exception:
            logger.exception(f"Could not notify referrer '{referrer.id}' — referral is saved")

        return referrer

    def _define_referral_level(self, parent_level: Optional[ReferralLevel]) -> ReferralLevel:
        if parent_level is None:
            return ReferralLevel.FIRST

        next_level_value = parent_level.value + 1
        max_level_value = max(item.value for item in ReferralLevel)

        if next_level_value > max_level_value:
            return ReferralLevel(parent_level.value)

        return ReferralLevel(next_level_value)
