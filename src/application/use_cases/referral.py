import base64
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from typing import Any, Final, Optional, cast

from loguru import logger
from PIL import Image
from qrcode import ERROR_CORRECT_H, QRCode  # type: ignore[attr-defined]

from src.application.common import EventPublisher, Interactor
from src.application.common.dao import ReferralDao, SettingsDao, SubscriptionDao, UserDao
from src.application.common.uow import UnitOfWork
from src.application.dto import ReferralRewardDto, ReferralSettingsDto, TransactionDto, UserDto
from src.application.events import ReferralRewardFailedEvent, ReferralRewardReceivedEvent
from src.application.use_cases.subscription import (
    AddSubscriptionDuration,
    AddSubscriptionDurationDto,
)
from src.application.use_cases.user import ChangeUserPoints, ChangeUserPointsDto
from src.core.constants import ASSETS_DIR
from src.core.enums import (
    PurchaseType,
    ReferralAccrualStrategy,
    ReferralLevel,
    ReferralRewardStrategy,
    ReferralRewardType,
)


class ValidateReferralCode(Interactor[str, bool]):
    required_permission = None

    def __init__(self, user_dao: UserDao) -> None:
        self.user_dao = user_dao

    async def _execute(self, actor: UserDto, referral_code: str) -> bool:
        referrer = await self.user_dao.get_by_referral_code(referral_code)
        if not referrer or referrer.telegram_id == actor.telegram_id:
            logger.warning(
                f"Invalid referral code '{referral_code}' or self-referral by '{actor.telegram_id}'"
            )
            return False
        return True


class GenerateReferralQr(Interactor[str, str]):
    required_permission = None

    async def _execute(self, actor: UserDto, url: str) -> str:
        qr: Any = QRCode(
            version=1,
            error_correction=ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )

        qr.add_data(url)
        qr.make(fit=True)

        qr_img_raw = qr.make_image(fill_color="black", back_color="white")

        if hasattr(qr_img_raw, "get_image"):
            qr_img = cast(Image.Image, qr_img_raw.get_image())
        else:
            qr_img = cast(Image.Image, qr_img_raw)

        qr_img = qr_img.convert("RGB")

        logo_path = ASSETS_DIR / "logo.png"
        if logo_path.exists():
            logo = Image.open(logo_path).convert("RGBA")

            qr_width, qr_height = qr_img.size
            logo_size = int(qr_width * 0.2)
            logo = logo.resize((logo_size, logo_size), resample=Image.Resampling.LANCZOS)

            pos = ((qr_width - logo_size) // 2, (qr_height - logo_size) // 2)
            qr_img.paste(logo, pos, mask=logo)

        buffer = BytesIO()
        qr_img.save(buffer, format="PNG")
        qr_bytes = buffer.getvalue()
        qr_base64 = base64.b64encode(qr_bytes).decode("ascii")
        buffer.seek(0)

        logger.info(f"{actor.log} Generated referral QR for URL '{url}'")

        return qr_base64


@dataclass(frozen=True)
class CalculateReferralRewardDto:
    settings: ReferralSettingsDto
    transaction: TransactionDto
    config_value: int


class CalculateReferralReward(Interactor[CalculateReferralRewardDto, Optional[int]]):
    required_permission = None

    async def _execute(self, actor: UserDto, data: CalculateReferralRewardDto) -> Optional[int]:
        reward_strategy = data.settings.reward.strategy
        reward_type = data.settings.reward.type
        reward_amount: int

        if reward_strategy == ReferralRewardStrategy.AMOUNT:
            reward_amount = data.config_value

        elif reward_strategy == ReferralRewardStrategy.PERCENT:
            percentage = Decimal(data.config_value) / Decimal(100)

            if reward_type == ReferralRewardType.POINTS:
                base_amount = data.transaction.pricing.final_amount
                reward_amount = max(1, int(base_amount * percentage))

            elif reward_type == ReferralRewardType.EXTRA_DAYS:
                if data.transaction.plan_snapshot and data.transaction.plan_snapshot.duration:
                    base_amount = Decimal(data.transaction.plan_snapshot.duration)
                    reward_amount = max(1, int(base_amount * percentage))
                else:
                    logger.warning(
                        f"Cannot calculate extra days reward, plan duration is missing "
                        f"for transaction '{data.transaction.id}'"
                    )
                    return None
            else:
                logger.warning(f"Unsupported reward type '{reward_type}' for PERCENT strategy")
                return None

        else:
            logger.warning(f"Unsupported reward strategy '{reward_strategy}'")
            return None

        logger.debug(
            f"Calculated '{reward_type}' reward '{reward_amount}' for transaction "
            f"'{data.transaction.id}' using '{reward_strategy}' strategy"
        )
        return reward_amount


@dataclass(frozen=True)
class GiveReferrerRewardDto:
    user_telegram_id: int
    reward: ReferralRewardDto
    referred_name: str


class GiveReferrerReward(Interactor[GiveReferrerRewardDto, None]):
    required_permission = None

    def __init__(
        self,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        referral_dao: ReferralDao,
        event_publisher: EventPublisher,
        change_user_points: ChangeUserPoints,
        add_subscription_duration: AddSubscriptionDuration,
    ) -> None:
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.referral_dao = referral_dao
        self.event_publisher = event_publisher
        self.change_user_points = change_user_points
        self.add_subscription_duration = add_subscription_duration

    async def _execute(self, actor: UserDto, data: GiveReferrerRewardDto) -> None:
        reward = data.reward
        user_telegram_id = data.user_telegram_id

        logger.info(
            f"{actor.log} Start applying reward of '{reward.amount}' "
            f"'{reward.type}' to user '{user_telegram_id}'"
        )
        if reward.type == ReferralRewardType.POINTS:
            await self.change_user_points.system(
                ChangeUserPointsDto(
                    telegram_id=user_telegram_id,
                    amount=reward.amount,
                )
            )

        elif reward.type == ReferralRewardType.EXTRA_DAYS:
            subscription = await self.subscription_dao.get_current(user_telegram_id)  # only active

            if not subscription or subscription.is_trial:
                logger.warning(
                    f"{actor.log} Current subscription not found "
                    f"for user '{user_telegram_id}', unable to add days"
                )

                event_failed = ReferralRewardFailedEvent(
                    name=data.referred_name,
                    value=reward.amount,
                    reward_type=reward.type,
                )

                await self.event_publisher.publish(event_failed)
                return

            logger.info(
                f"{actor.log} Current subscription found for user '{user_telegram_id}', "
                f"expire date '{subscription.expire_at}'"
            )

            await self.add_subscription_duration.system(
                AddSubscriptionDurationDto(
                    telegram_id=user_telegram_id,
                    days=reward.amount,
                ),
            )

        else:
            raise ValueError(
                f"Failed to apply reward: unknown type '{reward.type}' "
                f"for user '{user_telegram_id}'"
            )

        event_reward = ReferralRewardReceivedEvent(
            name=data.referred_name,
            value=reward.amount,
            reward_type=reward.type,
        )

        await self.event_publisher.publish(event_reward)

        await self.referral_dao.mark_reward_as_issued(reward.id)  # type: ignore[arg-type]
        logger.info(f"{actor.log} Finished applying reward to user '{user_telegram_id}'")


@dataclass(frozen=True)
class AssignReferralRewardsDto:
    user: UserDto
    transaction: TransactionDto


class AssignReferralRewards(Interactor[AssignReferralRewardsDto, None]):
    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        settings_dao: SettingsDao,
        user_dao: UserDao,
        referral_dao: ReferralDao,
        calculate_referral_reward: CalculateReferralReward,
        give_referrer_reward: GiveReferrerReward,
    ) -> None:
        self.uow = uow
        self.settings_dao = settings_dao
        self.user_dao = user_dao
        self.referral_dao = referral_dao
        self.calculate_referral_reward = calculate_referral_reward
        self.give_referrer_reward = give_referrer_reward

    async def _execute(self, actor: UserDto, data: AssignReferralRewardsDto) -> None:
        settings = await self.settings_dao.get()

        if (
            settings.referral.accrual_strategy == ReferralAccrualStrategy.ON_FIRST_PAYMENT
            and data.transaction.purchase_type != PurchaseType.NEW
        ):
            logger.info(
                f"Skip rewards: transaction '{data.transaction.id}' purchase type "
                f"'{data.transaction.purchase_type}' is not NEW"
            )
            return

        referral, parent = await self.referral_dao.get_referral_chain(data.user.telegram_id)

        if not referral:
            logger.info(f"User '{data.user.telegram_id}' not referred; reward assignment skipped")
            return

        reward_type = settings.referral.reward.type
        reward_chain = {ReferralLevel.FIRST: referral.referrer}

        if parent:
            reward_chain[ReferralLevel.SECOND] = parent.referrer

        for level, referrer in reward_chain.items():
            if level > settings.referral.level:
                continue

            config_value = settings.referral.reward.config.get(level)
            if config_value is None:
                logger.info(f"No reward config for level '{level.name}'")
                continue

            reward_amount = await self.calculate_referral_reward.system(
                CalculateReferralRewardDto(
                    settings=settings.referral,
                    transaction=data.transaction,
                    config_value=config_value,
                )
            )

            if not reward_amount or reward_amount <= 0:
                logger.warning(
                    f"Reward amount <= 0 for referrer '{referrer.telegram_id}', "
                    f"level '{level.name}'"
                )
                continue

            async with self.uow:
                reward = await self.referral_dao.create_reward(
                    reward=ReferralRewardDto(
                        user_telegram_id=referrer.telegram_id,
                        type=reward_type,
                        amount=reward_amount,
                        is_issued=False,
                    ),
                    referral_id=referral.id,  # type: ignore[arg-type]
                )

                await self.uow.commit()

                await self.give_referrer_reward.system(
                    GiveReferrerRewardDto(
                        user_telegram_id=referrer.telegram_id,
                        reward=reward,
                        referred_name=data.user.name,
                    )
                )

            logger.info(
                f"Issued '{reward_type}' reward '{reward_amount}' for referrer "
                f"'{referrer.telegram_id}' (level '{level.name}')"
            )


REFERRAL_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    ValidateReferralCode,
    GenerateReferralQr,
    CalculateReferralReward,
    GiveReferrerReward,
    AssignReferralRewards,
)
