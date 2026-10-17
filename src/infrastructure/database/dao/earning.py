from dataclasses import asdict
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.common.dao.earning import EarningDao
from src.application.dto.earning import ChannelClaimDto, ChannelTaskDto, EarningStatisticsDto
from src.core.utils.time import datetime_now
from src.infrastructure.database.models.earning import ChannelClaim, ChannelTask
from src.infrastructure.database.models.user import User


class EarningDaoImpl(EarningDao):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _task_dto(row: ChannelTask, count: int, completed: int) -> ChannelTaskDto:
        return ChannelTaskDto(
            **{
                key: getattr(row, key)
                for key in ChannelTaskDto.__dataclass_fields__
                if key not in {"claims_count", "completed_claims_count"}
            },
            claims_count=count or 0,
            completed_claims_count=completed or 0,
        )

    async def list_tasks(self) -> list[ChannelTaskDto]:
        counts = (
            select(
                ChannelClaim.task_id,
                func.count().label("count"),
                func.count().filter(ChannelClaim.status == "completed").label("completed"),
            )
            .group_by(ChannelClaim.task_id)
            .subquery()
        )
        rows = await self.session.execute(
            select(
                ChannelTask, func.coalesce(counts.c.count, 0), func.coalesce(counts.c.completed, 0)
            )
            .outerjoin(counts, counts.c.task_id == ChannelTask.id)
            .where(ChannelTask.deleted.is_(False))
            .order_by(ChannelTask.id)
        )
        return [self._task_dto(row, count, completed) for row, count, completed in rows]

    async def get_statistics(self, now: datetime) -> EarningStatisticsDto:
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = day_start - timedelta(days=now.weekday())
        month_start = day_start.replace(day=1)
        row = (
            await self.session.execute(
                select(
                    func.count().filter(ChannelClaim.completed_at >= day_start),
                    func.count().filter(ChannelClaim.completed_at >= week_start),
                    func.count().filter(ChannelClaim.completed_at >= month_start),
                    func.count(),
                )
                .select_from(ChannelClaim)
                .where(
                    ChannelClaim.status == "completed",
                    ChannelClaim.completed_at <= now,
                )
            )
        ).one()
        return EarningStatisticsDto(daily=row[0], weekly=row[1], monthly=row[2], total=row[3])

    async def get_task(self, task_id: int, *, lock: bool = False) -> ChannelTaskDto | None:
        stmt = select(ChannelTask).where(ChannelTask.id == task_id)
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        row = await self.session.scalar(stmt)
        if row is None:
            return None
        counts = (
            await self.session.execute(
                select(func.count(), func.count().filter(ChannelClaim.status == "completed"))
                .select_from(ChannelClaim)
                .where(ChannelClaim.task_id == row.id)
            )
        ).one()
        return self._task_dto(row, counts[0], counts[1])

    async def save_task(self, task: ChannelTaskDto) -> ChannelTaskDto:
        values = asdict(task)
        values.pop("id")
        values.pop("claims_count")
        values.pop("completed_claims_count")
        row = await self.session.get(ChannelTask, task.id) if task.id else None
        if row is None:
            row = ChannelTask(**values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        await self.session.flush()
        saved = await self.get_task(row.id)
        assert saved is not None
        return saved

    async def lock_user(self, user_id: int) -> None:
        await self.session.execute(select(User.id).where(User.id == user_id).with_for_update())

    @staticmethod
    def _claim_dto(row: ChannelClaim) -> ChannelClaimDto:
        return ChannelClaimDto(
            **{key: getattr(row, key) for key in ChannelClaimDto.__dataclass_fields__}
        )

    async def get_claims(self, user_id: int) -> list[ChannelClaimDto]:
        rows = await self.session.scalars(
            select(ChannelClaim).where(ChannelClaim.user_id == user_id)
        )
        return [self._claim_dto(row) for row in rows]

    async def get_pending_claims(self) -> list[ChannelClaimDto]:
        rows = await self.session.scalars(
            select(ChannelClaim).where(ChannelClaim.status != "completed").order_by(ChannelClaim.id)
        )
        return [self._claim_dto(row) for row in rows]

    async def get_claim(self, task_id: int, user_id: int) -> ChannelClaimDto | None:
        row = await self.session.scalar(
            select(ChannelClaim)
            .where(ChannelClaim.task_id == task_id, ChannelClaim.user_id == user_id)
            .execution_options(populate_existing=True)
        )
        return self._claim_dto(row) if row else None

    async def save_claim(self, claim: ChannelClaimDto) -> None:
        row = await self.session.scalar(
            select(ChannelClaim).where(
                ChannelClaim.task_id == claim.task_id, ChannelClaim.user_id == claim.user_id
            )
        )
        if row is None:
            row = ChannelClaim(**asdict(claim))
            self.session.add(row)
        else:
            for key, value in asdict(claim).items():
                setattr(row, key, value)
        if claim.status == "completed" and row.completed_at is None:
            row.completed_at = datetime_now()
        await self.session.flush()

    async def reset_completed_claims(self, task_id: int) -> None:
        # Pending claims may already contain partially granted rewards.
        await self.session.execute(
            delete(ChannelClaim).where(
                ChannelClaim.task_id == task_id,
                ChannelClaim.status == "completed",
            )
        )
