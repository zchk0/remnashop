from datetime import timedelta
from typing import Optional, cast
from uuid import UUID

from adaptix import Retort
from adaptix.conversion import ConversionRetort
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.common.dao import TransactionDao
from src.application.dto import TransactionDto
from src.core.enums import TransactionStatus
from src.core.utils.time import datetime_now
from src.infrastructure.database.models import Transaction


class TransactionDaoImpl(TransactionDao):
    def __init__(
        self,
        session: AsyncSession,
        retort: Retort,
        conversion_retort: ConversionRetort,
        redis: Redis,
    ) -> None:
        self.session = session
        self.retort = retort
        self.conversion_retort = conversion_retort
        self.redis = redis

        self._convert_to_dto = self.conversion_retort.get_converter(Transaction, TransactionDto)
        self._convert_to_dto_list = self.conversion_retort.get_converter(
            list[Transaction],
            list[TransactionDto],
        )

    async def create(self, transaction: TransactionDto) -> TransactionDto:
        transaction_data = self.retort.dump(transaction)
        db_transaction = Transaction(**transaction_data)

        self.session.add(db_transaction)
        await self.session.flush()

        logger.debug(f"Created new transaction '{transaction.payment_id}'")
        return self._convert_to_dto(db_transaction)

    async def get_by_payment_id(self, payment_id: UUID) -> Optional[TransactionDto]:
        stmt = select(Transaction).where(Transaction.payment_id == payment_id)
        db_transaction = await self.session.scalar(stmt)

        if db_transaction:
            logger.debug(f"Transaction '{payment_id}' found")
            return self._convert_to_dto(db_transaction)

        logger.debug(f"Transaction '{payment_id}' not found")
        return None

    async def get_by_user(self, telegram_id: int) -> list[TransactionDto]:
        stmt = select(Transaction).where(Transaction.user_telegram_id == telegram_id)
        result = await self.session.scalars(stmt)
        db_transactions = cast(list, result.all())

        logger.debug(f"Retrieved '{len(db_transactions)}' transactions for user '{telegram_id}'")
        return self._convert_to_dto_list(db_transactions)

    async def get_all(self, limit: int = 100, offset: int = 0) -> list[TransactionDto]:
        stmt = (
            select(Transaction).limit(limit).offset(offset).order_by(Transaction.created_at.desc())
        )
        result = await self.session.scalars(stmt)
        db_transactions = cast(list, result.all())

        logger.debug(
            f"Retrieved '{len(db_transactions)}' transactions "
            f"with limit '{limit}' and offset '{offset}'"
        )
        return self._convert_to_dto_list(db_transactions)

    async def get_by_status(self, status: TransactionStatus) -> list[TransactionDto]:
        stmt = select(Transaction).where(Transaction.status == status)
        result = await self.session.scalars(stmt)
        db_transactions = cast(list, result.all())

        logger.debug(f"Found '{len(db_transactions)}' transactions with status '{status}'")
        return self._convert_to_dto_list(db_transactions)

    async def update_status(
        self,
        payment_id: UUID,
        status: TransactionStatus,
    ) -> Optional[TransactionDto]:
        stmt = (
            update(Transaction)
            .where(Transaction.payment_id == payment_id)
            .values(status=status)
            .returning(Transaction)
        )
        db_transaction = await self.session.scalar(stmt)

        if db_transaction:
            logger.debug(f"Transaction '{payment_id}' status updated to '{status}'")
            return self._convert_to_dto(db_transaction)

        logger.warning(f"Failed to update transaction '{payment_id}': not found")
        return None

    async def exists(self, payment_id: UUID) -> bool:
        stmt = select(select(Transaction).where(Transaction.payment_id == payment_id).exists())
        is_exists = await self.session.scalar(stmt) or False

        logger.debug(f"Transaction '{payment_id}' existence status is '{is_exists}'")
        return is_exists

    async def cancel_old(self, minutes: int = 30) -> int:
        threshold = datetime_now() - timedelta(minutes=minutes)

        stmt = (
            update(Transaction)
            .where(Transaction.status == TransactionStatus.PENDING)
            .where(Transaction.created_at < threshold)
            .values(status=TransactionStatus.CANCELED)
        )
        result = await self.session.execute(stmt)
        count = result.rowcount  # type: ignore[attr-defined]

        if count > 0:
            logger.debug(f"Cancelled '{count}' pending transactions older than '{minutes}' minutes")
        else:
            logger.debug(f"No pending transactions older than '{minutes}' minutes found to cancel")

        return cast(int, count)

    async def count(self) -> int:
        stmt = select(func.count()).select_from(Transaction)
        total = await self.session.scalar(stmt) or 0

        logger.debug(f"Total transactions count is '{total}'")
        return total
