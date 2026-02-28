from typing import Any, Awaitable, Callable, Optional

from aiogram.types import CallbackQuery, Message, TelegramObject
from aiogram.types import User as AiogramUser
from aiogram_dialog.utils import remove_intent_id
from dishka import AsyncContainer
from loguru import logger

from src.application.dto import TempUserDto
from src.application.use_cases.access.queries.availability import CheckAccess, CheckAccessDto
from src.application.use_cases.referral.queries.code import ValidateReferralCode
from src.core.constants import CONTAINER_KEY, PAYMENT_PREFIX, REFERRAL_PREFIX
from src.core.enums import MiddlewareEventType

from .base import EventTypedMiddleware


class AccessMiddleware(EventTypedMiddleware):
    __event_types__ = [MiddlewareEventType.MESSAGE, MiddlewareEventType.CALLBACK_QUERY]

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
        check_access = await container.get(CheckAccess)
        validate_referral_code = await container.get(ValidateReferralCode)

        if await check_access.system(
            CheckAccessDto(
                temp_user=TempUserDto.from_aiogram(aiogram_user),
                is_payment_event=self._is_payment_event(event),
                is_referral_event=await self.is_referral_event(event, validate_referral_code),
            )
        ):
            return await handler(event, data)

    def _is_payment_event(self, event: TelegramObject) -> bool:
        if not isinstance(event, CallbackQuery) or not event.data:
            return False

        callback_data = remove_intent_id(event.data)

        if callback_data[-1].startswith(PAYMENT_PREFIX):
            logger.debug(f"Detected payment event '{callback_data}'")
            return True

        return False

    async def is_referral_event(
        self,
        event: TelegramObject,
        validate_referral_code: ValidateReferralCode,
    ) -> bool:
        if not isinstance(event, Message) or not event.text:
            return False

        parts = event.text.split()
        if len(parts) <= 1:
            return False

        code = parts[1]

        if code.startswith(REFERRAL_PREFIX):
            logger.debug(f"Detected referral event '{code}'")
            return await validate_referral_code.system(code)

        return False
