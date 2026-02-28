from dataclasses import dataclass
from typing import Optional, Self

from aiogram.types import ChatMemberUpdated, TelegramObject
from aiogram.types import User as AiogramUser
from loguru import logger

from src.application.common import Cryptographer, EventPublisher, Interactor
from src.application.common.dao import UserDao
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto
from src.application.events import UserRegisteredEvent
from src.application.use_cases.referral.commands.attachment import AttachReferral, AttachReferralDto
from src.application.use_cases.referral.queries.code import GetReferralCodeFromEvent
from src.core.config import AppConfig
from src.core.enums import Locale, Role


@dataclass(frozen=True)
class GetOrCreateUserDto:
    telegram_id: int
    username: Optional[str]
    full_name: str
    language_code: Optional[str]
    event: TelegramObject

    @classmethod
    def from_aiogram(cls, user: AiogramUser, event: TelegramObject) -> Self:
        return cls(
            telegram_id=user.id,
            username=user.username,
            full_name=user.full_name,
            language_code=user.language_code,
            event=event,
        )


class GetOrCreateUser(Interactor[GetOrCreateUserDto, Optional[UserDto]]):
    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        user_dao: UserDao,
        config: AppConfig,
        cryptographer: Cryptographer,
        event_publisher: EventPublisher,
        get_referral_code_from_event: GetReferralCodeFromEvent,
        attach_referral: AttachReferral,
    ) -> None:
        self.uow = uow
        self.user_dao = user_dao
        self.config = config
        self.cryptographer = cryptographer
        self.event_publisher = event_publisher
        self.get_referral_code_from_event = get_referral_code_from_event
        self.attach_referral = attach_referral

    async def _execute(self, actor: UserDto, data: GetOrCreateUserDto) -> Optional[UserDto]:
        async with self.uow:
            user = await self.user_dao.get_by_telegram_id(data.telegram_id)
            if user:
                return user

            if data.event.__class__.__name__ == ChatMemberUpdated.__name__:
                logger.debug(
                    f"Skipping user creation for '{data.telegram_id}' "
                    f"due to '{ChatMemberUpdated.__name__}' event"
                )
                return None

            user_dto = self._create_user_dto(data)
            user = await self.user_dao.create(user_dto)
            await self.uow.commit()

        referrer = None
        referral_code = await self.get_referral_code_from_event.system(data.event)
        if referral_code:
            referrer = await self.attach_referral.system(
                AttachReferralDto(user.telegram_id, referral_code)
            )

        await self.event_publisher.publish(
            UserRegisteredEvent(
                telegram_id=user.telegram_id,
                username=user.username,
                name=user.name,
                referrer_telegram_id=referrer.telegram_id if referrer else None,
                referrer_username=referrer.username if referrer else None,
                referrer_name=referrer.name if referrer else None,
            )
        )

        logger.info(f"New user '{user.telegram_id}' created")
        return user

    def _create_user_dto(self, data: GetOrCreateUserDto) -> UserDto:
        is_owner = data.telegram_id == self.config.bot.owner_id

        if data.language_code in self.config.locales:
            locale = Locale(data.language_code)
        else:
            locale = self.config.default_locale

        return UserDto(
            telegram_id=data.telegram_id,
            username=data.username,
            referral_code=self.cryptographer.generate_short_code(data.telegram_id),
            name=data.full_name,
            role=Role.OWNER if is_owner else Role.USER,
            language=locale,
        )
