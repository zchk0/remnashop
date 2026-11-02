from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import BroadcastDao, PaymentGatewayDao, TransactionDao
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto
from src.application.dto.payment_gateway import FlippayGatewaySettingsDto
from src.core.enums import PaymentGatewayType


class CancelOldTransactions(Interactor[None, None]):
    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        transaction_dao: TransactionDao,
        gateway_dao: PaymentGatewayDao,
    ) -> None:
        self.uow = uow
        self.transaction_dao = transaction_dao
        self.gateway_dao = gateway_dao

    async def _execute(self, actor: UserDto, data: None) -> None:
        async with self.uow:
            gateway_timeouts = {}
            gateway = await self.gateway_dao.get_by_type(PaymentGatewayType.FLIPPAY)
            if gateway and isinstance(gateway.settings, FlippayGatewaySettingsDto):
                gateway_timeouts[gateway.type] = gateway.settings.payment_timeout_minutes
            await self.transaction_dao.cancel_old(gateway_timeouts=gateway_timeouts)
            await self.uow.commit()

        logger.info("Canceled old transactions from database")


class ClearOldBroadcasts(Interactor[None, None]):
    required_permission = None

    def __init__(self, uow: UnitOfWork, broadcast_dao: BroadcastDao) -> None:
        self.uow = uow
        self.broadcast_dao = broadcast_dao

    async def _execute(self, actor: UserDto, data: None) -> None:
        async with self.uow:
            await self.broadcast_dao.delete_old()
            await self.uow.commit()

        logger.info("Cleaned up old broadcasts from database")
