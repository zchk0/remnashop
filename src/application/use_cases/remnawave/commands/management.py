from dataclasses import dataclass

from loguru import logger
from remnapy import RemnawaveSDK

from src.application.common import Interactor, Remnawave
from src.application.common.dao import SubscriptionDao
from src.application.common.policy import Permission
from src.application.dto import UserDto


@dataclass(frozen=True)
class DeleteUserDeviceDto:
    telegram_id: int
    hwid: str


class DeleteUserDevice(Interactor[DeleteUserDeviceDto, bool]):
    required_permission = Permission.USER_EDITOR

    def __init__(self, subscription_dao: SubscriptionDao, remnawave: Remnawave):
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave

    async def _execute(self, actor: UserDto, data: DeleteUserDeviceDto) -> bool:
        subscription = await self.subscription_dao.get_current(data.telegram_id)

        if not subscription:
            raise ValueError(f"Subscription for user '{data.telegram_id}' not found")

        remaining_devices = await self.remnawave.delete_device(
            subscription.user_remna_id,
            data.hwid,
        )

        logger.info(f"{actor.log} Deleted device '{data.hwid}' for user '{data.telegram_id}'")
        return bool(remaining_devices)


class ResetUserTraffic(Interactor[int, None]):
    required_permission = Permission.USER_EDITOR

    def __init__(
        self,
        subscription_dao: SubscriptionDao,
        remnawave_sdk: RemnawaveSDK,
    ):
        self.subscription_dao = subscription_dao
        self.remnawave_sdk = remnawave_sdk

    async def _execute(self, actor: UserDto, telegram_id: int) -> None:
        subscription = await self.subscription_dao.get_current(telegram_id)
        if not subscription:
            raise ValueError(f"Subscription for user '{telegram_id}' not found")

        try:
            await self.remnawave_sdk.users.reset_user_traffic(subscription.user_remna_id)
        except Exception as e:
            logger.error(f"Failed to reset traffic in Remnawave for user '{telegram_id}': {e}")
            raise

        logger.info(f"{actor.log} Reset traffic for user '{telegram_id}'")
