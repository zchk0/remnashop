from dataclasses import dataclass
from uuid import UUID

from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import BroadcastDao
from src.application.common.policy import Permission
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto
from src.core.enums import BroadcastStatus


@dataclass(frozen=True)
class DeleteBroadcastResultDto:
    total: int
    deleted: int
    failed: int


class DeleteBroadcast(Interactor[UUID, DeleteBroadcastResultDto]):
    required_permission = Permission.BROADCAST

    def __init__(
        self,
        uow: UnitOfWork,
        broadcast_dao: BroadcastDao,
    ):
        self.uow = uow
        self.broadcast_dao = broadcast_dao

    async def _execute(self, actor: UserDto, data: UUID) -> DeleteBroadcastResultDto:
        from src.infrastructure.taskiq.tasks.broadcast import delete_broadcast_task  # noqa: PLC0415

        async with self.uow:
            broadcast = await self.broadcast_dao.get_by_task_id(data)

            if not broadcast:
                logger.error(f"{actor.log} Failed to find broadcast '{data}' for deletion")
                raise ValueError(f"Broadcast '{data}' not found")

            if broadcast.status == BroadcastStatus.DELETED:
                logger.warning(f"{actor.log} Broadcast '{data}' is already deleted")
                raise ValueError("Broadcast already deleted")

            await self.broadcast_dao.update_status(data, BroadcastStatus.DELETED)
            await self.uow.commit()

        logger.info(f"{actor.log} Initiated deletion for broadcast '{data}'")

        task = await delete_broadcast_task.kiq(broadcast)  # type: ignore[call-overload]
        result = await task.wait_result()
        counts = result.return_value

        logger.info(
            f"{actor.log} Finished deletion for '{data}' "
            f"(total: '{counts[0]}', deleted: '{counts[1]}', failed: '{counts[2]}')"
        )
        return DeleteBroadcastResultDto(total=counts[0], deleted=counts[1], failed=counts[2])
