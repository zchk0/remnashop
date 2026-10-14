from typing import TYPE_CHECKING, Annotated, NewType, TypeAlias, Union

from aiogram.types import (
    ForceReply,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from pydantic import PlainValidator
from remnapy.models import UserResponseDto
from remnapy.models.hwid import HwidDeviceDto
from remnapy.models.webhook import UserDto as UserWebhookDto

from src.core.enums import Locale, SystemNotificationType, UserNotificationType
from src.infrastructure.remnawave_v3.models import HwidDevice
from src.infrastructure.remnawave_v3.models import User as PanelV3User

if TYPE_CHECKING:
    ListStr: TypeAlias = list[str]
    ListLocale: TypeAlias = list[Locale]
else:
    ListStr = NewType("ListStr", list[str])
    ListLocale = NewType("ListLocale", list[Locale])

AnyKeyboard: TypeAlias = Union[
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    ForceReply,
]


NotificationType: TypeAlias = Union[SystemNotificationType, UserNotificationType]

RemnaUserDto: TypeAlias = Union[UserWebhookDto, UserResponseDto, PanelV3User]
RemnaDeviceDto: TypeAlias = Union[HwidDevice, HwidDeviceDto]

StringList: TypeAlias = Annotated[
    ListStr, PlainValidator(lambda x: [s.strip() for s in x.split(",")])
]
LocaleList: TypeAlias = Annotated[
    ListLocale,
    PlainValidator(
        func=lambda x: [Locale(loc.strip()) for loc in x.split(",")] if isinstance(x, str) else x
    ),
]
