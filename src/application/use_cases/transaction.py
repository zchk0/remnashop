from typing import Final

from loguru import logger

from src.application.common import Interactor
from src.application.common.dao.transaction import TransactionDao
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto


class CancelOldTransactions(Interactor[None, None]):
    required_permission = None

    def __init__(self, uow: UnitOfWork, transaction_dao: TransactionDao):
        self.uow = uow
        self.transaction_dao = transaction_dao

    async def _execute(self, actor: UserDto, data: None) -> None:
        async with self.uow:
            await self.transaction_dao.cancel_old()
            await self.uow.commit()

        logger.info("Canceled up old transactions from database")


REFERRAL_USE_CASES: Final[tuple[type[Interactor], ...]] = (CancelOldTransactions,)
