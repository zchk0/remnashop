from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import UserDao
from src.application.common.policy import Permission
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto
from src.core.config import AppConfig
from src.core.enums import Locale


class SetUserLanguage(Interactor[Locale, UserDto]):
    required_permission = Permission.PUBLIC

    def __init__(self, uow: UnitOfWork, user_dao: UserDao, config: AppConfig) -> None:
        self.uow = uow
        self.user_dao = user_dao
        self.config = config

    async def _execute(self, actor: UserDto, data: Locale) -> UserDto:
        if data not in self.config.locales:
            raise ValueError(f"Unsupported language '{data}'")

        async with self.uow:
            user = await self.user_dao.get_by_id(actor.id)
            if user is None:
                raise ValueError(f"User '{actor.id}' not found")

            user.language = data
            user.is_language_manual = True
            updated_user = await self.user_dao.update(user)
            if updated_user is None:
                raise ValueError(f"Could not update language for user '{actor.id}'")
            await self.uow.commit()

        logger.info(f"{actor.log} Selected bot language '{data}'")
        return updated_user
