import asyncio
from dataclasses import dataclass
from uuid import UUID

from loguru import logger
from remnapy import RemnawaveSDK
from remnapy.models import DeleteUserAllHwidDeviceRequestDto

from src.application.common import Interactor
from src.application.common.dao import SubscriptionDao
from src.application.common.policy import Permission
from src.application.common.remnawave import Remnawave
from src.application.common.uow import UnitOfWork
from src.application.dto import RemnaSubscriptionDto, UserDto


@dataclass(frozen=True)
class DeleteUserDeviceDto:
    telegram_id: int
    hwid: str


class DeleteUserDevice(Interactor[DeleteUserDeviceDto, bool]):
    required_permission = Permission.PUBLIC

    def __init__(self, subscription_dao: SubscriptionDao, remnawave: Remnawave):
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave

    async def _execute(self, actor: UserDto, data: DeleteUserDeviceDto) -> bool:
        current_subscription = await self.subscription_dao.get_current(data.telegram_id)

        if not current_subscription:
            raise ValueError(f"Subscription for user '{data.telegram_id}' not found")

        remaining_devices = await self.remnawave.delete_device(
            current_subscription.user_remna_id,
            data.hwid,
        )

        logger.info(f"{actor.log} Deleted device '{data.hwid}' for user '{data.telegram_id}'")
        return bool(remaining_devices)


class DeleteUserAllDevices(Interactor[None, None]):
    required_permission = Permission.PUBLIC

    def __init__(self, subscription_dao: SubscriptionDao, remnawave_sdk: RemnawaveSDK) -> None:
        self.subscription_dao = subscription_dao
        self.remnawave_sdk = remnawave_sdk

    async def _execute(self, actor: UserDto, data: None) -> None:
        current_subscription = await self.subscription_dao.get_current(actor.telegram_id)

        if not current_subscription:
            raise ValueError(
                f"User '{actor.telegram_id}' has no active subscription or device limit unlimited"
            )

        result = await self.remnawave_sdk.hwid.delete_all_hwid_user(
            DeleteUserAllHwidDeviceRequestDto(user_uuid=current_subscription.user_remna_id)
        )

        logger.info(f"{actor.log} Deleted all devices ({result.total})")


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


class ReissueSubscription(Interactor[None, None]):
    required_permission = Permission.PUBLIC
    FETCH_ATTEMPTS = 5
    FETCH_DELAY_SECONDS = 1

    def __init__(
        self,
        uow: UnitOfWork,
        subscription_dao: SubscriptionDao,
        remnawave: Remnawave,
    ) -> None:
        self.uow = uow
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave

    async def _execute(self, actor: UserDto, data: None) -> None:
        current_subscription = await self.subscription_dao.get_current(actor.telegram_id)

        if not current_subscription:
            raise ValueError(f"No active subscription for user '{actor.telegram_id}'")

        previous_url = current_subscription.url
        await self.remnawave.revoke_subscription(current_subscription.user_remna_id)
        synced = await self._sync_reissued_subscription(
            telegram_id=actor.telegram_id,
            user_remna_id=current_subscription.user_remna_id,
            previous_url=previous_url,
        )

        if not synced:
            logger.warning(
                f"{actor.log} Subscription was reissued, but updated URL was not synced immediately"
            )

        logger.info(f"{actor.log} Reissued subscription")

    async def _sync_reissued_subscription(
        self,
        telegram_id: int,
        user_remna_id: UUID,
        previous_url: str,
    ) -> bool:
        for attempt in range(1, self.FETCH_ATTEMPTS + 1):
            remna_user = await self.remnawave.get_user_by_uuid(user_remna_id)

            if remna_user:
                remna_subscription = RemnaSubscriptionDto.from_remna_user(remna_user)

                if remna_subscription.url != previous_url:
                    async with self.uow:
                        subscription = await self.subscription_dao.get_current(telegram_id)

                        if not subscription:
                            logger.warning(
                                f"Current subscription for user '{telegram_id}' disappeared during reissue sync"
                            )
                            return False

                        subscription = self.remnawave.apply_sync(subscription, remna_subscription)
                        await self.subscription_dao.update(subscription)
                        await self.uow.commit()
                    return True

            if attempt < self.FETCH_ATTEMPTS:
                await asyncio.sleep(self.FETCH_DELAY_SECONDS)

        return False
