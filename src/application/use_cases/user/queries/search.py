from dataclasses import dataclass
from typing import Optional

from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import UserDao
from src.application.common.policy import Permission
from src.application.dto import UserDto
from src.core.constants import REMNASHOP_PREFIX


@dataclass(frozen=True)
class SearchUsersDto:
    query: Optional[str] = None
    forward_from_id: Optional[int] = None
    is_forwarded_from_bot: bool = False


class SearchUsers(Interactor[SearchUsersDto, list[UserDto]]):
    required_permission = Permission.USER_SEARCH

    def __init__(self, user_dao: UserDao):
        self.user_dao = user_dao

    async def _execute(self, actor: UserDto, data: SearchUsersDto) -> list[UserDto]:
        found_users = []

        if data.forward_from_id and not data.is_forwarded_from_bot:
            telegram_id = data.forward_from_id
            user = await self.user_dao.get_by_telegram_id(telegram_id)
            if user:
                found_users.append(user)
                logger.info(f"Search by forwarded message, found user '{telegram_id}'")
            else:
                logger.warning(f"Search by forwarded message, user '{telegram_id}' not found")

        elif data.query:
            query = data.query.strip()

            if query.isdigit():
                telegram_id = int(query)
                user = await self.user_dao.get_by_telegram_id(telegram_id)
                if user:
                    found_users.append(user)
                    logger.info(f"Searched by Telegram ID '{telegram_id}', user found")
                else:
                    logger.warning(f"Searched by Telegram ID '{telegram_id}', user not found")

            elif query.startswith(REMNASHOP_PREFIX):
                try:
                    telegram_id = int(query.split("_", maxsplit=1)[1])
                    user = await self.user_dao.get_by_telegram_id(telegram_id)
                    if user:
                        found_users.append(user)
                        logger.info(f"Searched by Remnashop ID '{telegram_id}', user found")
                    else:
                        logger.warning(f"Searched by Remnashop ID '{telegram_id}', user not found")
                except (IndexError, ValueError):
                    logger.warning(f"Failed to parse Remnashop ID from query '{query}'")

            else:
                found_users = await self.user_dao.get_by_partial_name(query)
                logger.info(
                    f"Searched users by partial name '{query}', found '{len(found_users)}' users"
                )

        return found_users
