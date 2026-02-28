from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import UserDao
from src.application.common.policy import Permission
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto


class AcceptRules(Interactor[None, None]):
    required_permission = Permission.PUBLIC

    def __init__(
        self,
        uow: UnitOfWork,
        user_dao: UserDao,
    ) -> None:
        self.uow = uow
        self.user_dao = user_dao

    async def _execute(self, actor: UserDto, data: None) -> None:
        async with self.uow:
            actor.is_rules_accepted = True
            await self.user_dao.update(actor)
            await self.uow.commit()

        logger.info(f"{actor.log} Accepted rules")
