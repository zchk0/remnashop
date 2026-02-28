from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from loguru import logger

from src.application.common import Interactor
from src.application.dto import ReferralSettingsDto, TransactionDto, UserDto
from src.core.enums import ReferralRewardStrategy, ReferralRewardType


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
