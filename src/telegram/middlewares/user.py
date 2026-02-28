from typing import Any, Awaitable, Callable, Optional

from aiogram.types import TelegramObject
from aiogram.types import User as AiogramUser
from dishka import AsyncContainer
from loguru import logger

from src.application.use_cases.user.commands.registration import GetOrCreateUser, GetOrCreateUserDto
from src.core.constants import CONTAINER_KEY, USER_KEY
from src.core.enums import MiddlewareEventType

from .base import EventTypedMiddleware


class UserMiddleware(EventTypedMiddleware):
    __event_types__ = [
        MiddlewareEventType.MESSAGE,
        MiddlewareEventType.CALLBACK_QUERY,
        MiddlewareEventType.ERROR,
        MiddlewareEventType.AIOGD_UPDATE,
        MiddlewareEventType.MY_CHAT_MEMBER,
        MiddlewareEventType.PRE_CHECKOUT_QUERY,
    ]

    async def middleware_logic(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        aiogram_user: Optional[AiogramUser] = self._get_aiogram_user(data)

        if aiogram_user is None or aiogram_user.is_bot:
            logger.warning("Terminating middleware: event from bot or missing user")
            return

        container: AsyncContainer = data[CONTAINER_KEY]
        get_or_create_user = await container.get(GetOrCreateUser)
        data[USER_KEY] = await get_or_create_user.system(
            GetOrCreateUserDto.from_aiogram(aiogram_user, event)
        )

        return await handler(event, data)
