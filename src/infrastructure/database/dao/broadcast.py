import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Optional, cast
from uuid import UUID

from adaptix import Retort
from adaptix.conversion import ConversionRetort
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import BigInteger, delete, func, literal, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from src.application.common.dao import BroadcastDao
from src.application.dto import BroadcastDto, BroadcastMessageDto
from src.core.enums import BroadcastMessageStatus, BroadcastStatus
from src.core.utils.time import datetime_now
from src.infrastructure.database.models import Broadcast, BroadcastDelivery, BroadcastMessage, User


class BroadcastDaoImpl(BroadcastDao):
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

        self._convert_to_dto = self.conversion_retort.get_converter(Broadcast, BroadcastDto)
        self._convert_to_dto_list = self.conversion_retort.get_converter(
            list[Broadcast], list[BroadcastDto]
        )
        self._convert_to_dto_messages_list = self.conversion_retort.get_converter(
            list[BroadcastMessage], list[BroadcastMessageDto]
        )

    async def create(self, broadcast: BroadcastDto) -> BroadcastDto:
        broadcast_data = self.retort.dump(broadcast)
        broadcast_data.pop("id", None)
        broadcast_data["campaign_id"] = broadcast.campaign_id or broadcast.task_id
        db_broadcast = Broadcast(**broadcast_data)

        self.session.add(db_broadcast)
        await self.session.flush()

        logger.debug(f"New broadcast task '{broadcast.task_id}' created")
        return self._convert_to_dto(db_broadcast)

    async def get_by_task_id(self, task_id: UUID) -> Optional[BroadcastDto]:
        stmt = (
            select(Broadcast)
            .where(Broadcast.task_id == task_id)
            .execution_options(populate_existing=True)
        )
        db_broadcast = await self.session.scalar(stmt)

        if db_broadcast:
            logger.debug(f"Broadcast task '{task_id}' found")
            return self._convert_to_dto(db_broadcast)

        logger.debug(f"Broadcast task '{task_id}' not found")
        return None

    async def get_all(self) -> list[BroadcastDto]:
        stmt = select(Broadcast).order_by(Broadcast.created_at.desc())
        result = await self.session.scalars(stmt)
        db_broadcasts = cast(list, result.all())

        logger.debug(f"Retrieved '{len(db_broadcasts)}' broadcasts")
        return self._convert_to_dto_list(db_broadcasts)

    async def get_delivered_telegram_ids(self, campaign_id: UUID) -> list[int]:
        stmt = select(BroadcastDelivery.telegram_id).where(
            BroadcastDelivery.campaign_id == campaign_id
        )
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def record_delivery(self, campaign_id: UUID, telegram_id: int) -> None:
        # Persist the receipt immediately, independently of the current batch.
        # Concurrent sends cannot share an AsyncSession.
        engine = self.session.bind
        if not isinstance(engine, AsyncEngine):
            raise RuntimeError("Broadcast delivery recording requires an async engine")
        stmt = (
            insert(BroadcastDelivery)
            .values(campaign_id=campaign_id, telegram_id=telegram_id)
            .on_conflict_do_nothing()
        )
        async with engine.begin() as connection:
            await connection.execute(stmt)

    @asynccontextmanager
    async def lock_campaign(self, campaign_id: UUID) -> AsyncIterator[None]:
        # A dedicated connection holds the lock across the sender's batch commits.
        # PostgreSQL releases it automatically on disconnect, rollback or cancellation.
        engine = self.session.bind
        if not isinstance(engine, AsyncEngine):
            raise RuntimeError("Broadcast campaign locking requires an async engine")
        lock_key = campaign_id.int & ((1 << 63) - 1)
        async with engine.connect() as connection, connection.begin():
            await connection.execute(text("SET LOCAL idle_in_transaction_session_timeout = 0"))
            lock_stmt = select(func.pg_try_advisory_xact_lock(literal(lock_key, type_=BigInteger)))
            while not await connection.scalar(lock_stmt):
                await asyncio.sleep(1)
            yield

    async def lock_campaign_transaction(self, campaign_id: UUID) -> None:
        # Hold the same campaign lock until the caller's unit of work commits.
        # This serializes repeat creation and automatic cleanup with worker tasks.
        lock_key = campaign_id.int & ((1 << 63) - 1)
        lock_stmt = select(func.pg_try_advisory_xact_lock(literal(lock_key, type_=BigInteger)))
        while not await self.session.scalar(lock_stmt):
            await asyncio.sleep(1)

    async def clear_finished_campaign(self, campaign_id: UUID) -> None:
        # The caller holds a campaign lock and commits before releasing it.
        # Deleted runs stay visible in the dashboard, but cannot be repeated.
        repeatable = select(Broadcast.id).where(
            Broadcast.campaign_id == campaign_id,
            Broadcast.status != BroadcastStatus.DELETED,
        )
        await self.session.execute(
            delete(BroadcastDelivery).where(
                BroadcastDelivery.campaign_id == campaign_id, ~repeatable.exists()
            )
        )

    async def update_status(self, task_id: UUID, status: BroadcastStatus) -> None:
        stmt = update(Broadcast).where(Broadcast.task_id == task_id).values(status=status)
        if status != BroadcastStatus.DELETED:
            # A delayed worker failure must not revive a deleted, already cleared run.
            stmt = stmt.where(Broadcast.status != BroadcastStatus.DELETED)
        await self.session.execute(stmt)
        logger.debug(f"Broadcast task '{task_id}' status updated to '{status}'")

    async def add_messages(
        self, task_id: UUID, messages: list[BroadcastMessageDto]
    ) -> list[BroadcastMessageDto]:
        broadcast_id_stmt = select(Broadcast.id).where(Broadcast.task_id == task_id)
        broadcast_id = await self.session.scalar(broadcast_id_stmt)

        if not broadcast_id:
            logger.error(f"Failed to add messages: broadcast task '{task_id}' not found")
            raise ValueError(f"Broadcast task '{task_id}' not found")

        db_messages = []
        for msg in messages:
            msg_data = self.retort.dump(msg)
            msg_data.pop("id", None)
            db_messages.append(BroadcastMessage(**msg_data, broadcast_id=broadcast_id))
        self.session.add_all(db_messages)
        await self.session.flush()

        logger.debug(f"Added '{len(messages)}' messages to broadcast task '{task_id}'")
        return self._convert_to_dto_messages_list(db_messages)

    async def update_stats(self, task_id: UUID, success_count: int, failed_count: int) -> None:
        stmt = (
            update(Broadcast)
            .where(Broadcast.task_id == task_id)
            .values(
                success_count=Broadcast.success_count + success_count,
                failed_count=Broadcast.failed_count + failed_count,
            )
        )
        await self.session.execute(stmt)
        logger.debug(
            f"Incremented stats for task '{task_id}': "
            f"success={success_count}, failed={failed_count}"
        )

    async def update_total_count(self, task_id: UUID, total: int) -> None:
        stmt = update(Broadcast).where(Broadcast.task_id == task_id).values(total_count=total)
        await self.session.execute(stmt)
        logger.debug(f"Set total_count for task '{task_id}' to '{total}'")

    async def delete_old(self, days: int = 14) -> int:
        threshold = datetime_now() - timedelta(days=days)

        expired = (
            Broadcast.created_at < threshold,
            Broadcast.status != BroadcastStatus.PROCESSING,
        )
        campaigns = await self.session.scalars(
            select(Broadcast.campaign_id).where(*expired).distinct().order_by(Broadcast.campaign_id)
        )
        count = 0
        for campaign_id in campaigns.all():
            await self.lock_campaign_transaction(campaign_id)
            result = await self.session.execute(
                delete(Broadcast)
                .where(Broadcast.campaign_id == campaign_id, *expired)
                .returning(Broadcast.id)
            )
            count += len(result.scalars().all())
            await self.clear_finished_campaign(campaign_id)

        if count > 0:
            logger.debug(f"Deleted '{count}' old broadcasts older than '{days}' days")
        else:
            logger.debug(f"No old broadcasts found to delete for the last '{days}' days")

        return count

    async def bulk_update_messages(self, messages: list[BroadcastMessageDto]) -> None:
        if not messages:
            logger.debug("No broadcast messages to update in bulk")
            return

        stmt = update(BroadcastMessage)

        data = [
            {
                "id": msg.id,
                "status": msg.status,
                "message_id": msg.message_id,
            }
            for msg in messages
        ]

        await self.session.execute(stmt, data, execution_options={"synchronize_session": None})
        delivered_ids = [
            msg.id
            for msg in messages
            if msg.message_id is not None
            and msg.status
            in (
                BroadcastMessageStatus.SENT,
                BroadcastMessageStatus.EDITED,
                BroadcastMessageStatus.DELETED,
            )
        ]
        if delivered_ids:
            await self._record_deliveries(delivered_ids)
        logger.debug(f"Bulk updated '{len(data)}' broadcast messages")

    async def _record_deliveries(self, message_ids: list[int]) -> None:
        telegram_id = func.coalesce(BroadcastMessage.user_telegram_id, User.telegram_id)
        stmt = (
            select(Broadcast.campaign_id, telegram_id.label("telegram_id"))
            .select_from(BroadcastMessage)
            .join(Broadcast, Broadcast.id == BroadcastMessage.broadcast_id)
            .join(User, User.id == BroadcastMessage.user_id)
            .where(BroadcastMessage.id.in_(message_ids), telegram_id.is_not(None))
            .distinct()
        )
        result = await self.session.execute(stmt)
        deliveries = [
            {"campaign_id": campaign_id, "telegram_id": telegram_id}
            for campaign_id, telegram_id in result.all()
        ]
        if deliveries:
            await self.session.execute(
                insert(BroadcastDelivery).values(deliveries).on_conflict_do_nothing()
            )
