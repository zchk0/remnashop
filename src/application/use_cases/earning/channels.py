from dataclasses import dataclass, replace

from src.application.common import Interactor
from src.application.common.dao.earning import EarningDao
from src.application.common.policy import Permission
from src.application.dto import UserDto
from src.application.dto.earning import ChannelTaskDto, EarningStatisticsDto
from src.core.utils.time import datetime_now


@dataclass(frozen=True)
class EarningChannelsDto:
    tasks: list[ChannelTaskDto]
    statistics: EarningStatisticsDto


class GetEarningChannels(Interactor[None, EarningChannelsDto]):
    required_permission = Permission.MANAGE_EARNING

    def __init__(self, earning_dao: EarningDao) -> None:
        self.earning_dao = earning_dao

    async def _execute(self, actor: UserDto, data: None) -> EarningChannelsDto:
        tasks = await self.earning_dao.list_tasks()
        statistics = await self.earning_dao.get_statistics(datetime_now())
        statistics = replace(
            statistics,
            active_tasks=sum(task.active and not task.is_completed for task in tasks),
            completed_tasks=sum(task.is_completed for task in tasks),
        )
        return EarningChannelsDto(tasks=tasks, statistics=statistics)
