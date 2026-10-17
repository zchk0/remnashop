from dataclasses import asdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.common.dao.earning import EarningDao
from src.application.dto.earning import ChannelClaimDto, ChannelTaskDto
from src.infrastructure.database.models.earning import ChannelClaim, ChannelTask
from src.infrastructure.database.models.user import User


class EarningDaoImpl(EarningDao):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _task_dto(self, row: ChannelTask) -> ChannelTaskDto:
        count = await self.session.scalar(
            select(func.count()).select_from(ChannelClaim).where(ChannelClaim.task_id == row.id)
        )
        return ChannelTaskDto(
            **{
                key: getattr(row, key)
                for key in ChannelTaskDto.__dataclass_fields__
                if key != "claims_count"
            },
            claims_count=count or 0,
        )

    async def list_tasks(self) -> list[ChannelTaskDto]:
        rows = await self.session.scalars(
            select(ChannelTask).where(ChannelTask.deleted.is_(False)).order_by(ChannelTask.id)
        )
        return [await self._task_dto(row) for row in rows]

    async def get_task(self, task_id: int, *, lock: bool = False) -> ChannelTaskDto | None:
        stmt = select(ChannelTask).where(ChannelTask.id == task_id)
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        row = await self.session.scalar(stmt)
        return await self._task_dto(row) if row else None

    async def save_task(self, task: ChannelTaskDto) -> ChannelTaskDto:
        values = asdict(task)
        values.pop("id")
        values.pop("claims_count")
        row = await self.session.get(ChannelTask, task.id) if task.id else None
        if row is None:
            row = ChannelTask(**values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        await self.session.flush()
        return await self._task_dto(row)

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
            self.session.add(ChannelClaim(**asdict(claim)))
        else:
            for key, value in asdict(claim).items():
                setattr(row, key, value)
        await self.session.flush()
