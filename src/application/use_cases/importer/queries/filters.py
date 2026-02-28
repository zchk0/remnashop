from loguru import logger

from src.application.common import Interactor
from src.application.common.policy import Permission
from src.application.dto import UserDto
from src.application.use_cases.importer.dto import ExportedUserDto
from src.core.utils.time import datetime_now


class SplitExportedUsers(
    Interactor[list[ExportedUserDto], tuple[list[ExportedUserDto], list[ExportedUserDto]]]
):
    required_permission = Permission.IMPORTER

    async def _execute(
        self,
        actor: UserDto,
        users: list[ExportedUserDto],
    ) -> tuple[list[ExportedUserDto], list[ExportedUserDto]]:
        now = datetime_now()
        active, expired = [], []

        for user in users:
            if user.expire_at > now:
                active.append(user)
            else:
                expired.append(user)

        logger.info(f"{actor.log} Split results: '{len(active)}' active, '{len(expired)}' expired")
        return active, expired
