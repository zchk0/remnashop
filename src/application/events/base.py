from dataclasses import asdict, dataclass, field
from datetime import datetime
from html import escape
from typing import Any
from uuid import UUID, uuid4

from src.application.dto import MessagePayloadDto, UserDto
from src.core.types import NotificationType
from src.core.utils.time import datetime_now


@dataclass(frozen=True, kw_only=True)
class BaseEvent:
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=datetime_now)

    notification_type: NotificationType = field(init=False)

    @property
    def event_type(self) -> str:
        return self.__class__.__name__

    @property
    def event_key(self) -> str:
        return f"event-{self.notification_type.value.lower().replace('_', '-')}"

    def _get_i18n_kwargs(self, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Escape event data before inserting it into HTML notification templates."""

        def escape_value(value: Any) -> Any:
            if isinstance(value, str):
                return escape(value)
            if isinstance(value, dict):
                return {key: escape_value(item) for key, item in value.items()}
            if isinstance(value, list):
                return [escape_value(item) for item in value]
            if isinstance(value, tuple):
                return tuple(escape_value(item) for item in value)
            return value

        source = asdict(self) if data is None else data
        return {key: escape_value(value) for key, value in source.items()}

    def as_payload(self, *args: Any, **kwargs: Any) -> "MessagePayloadDto":
        return MessagePayloadDto(
            i18n_key=self.event_key,
            i18n_kwargs=self._get_i18n_kwargs(),
            disable_default_markup=False,
            delete_after=None,
        )


@dataclass(frozen=True, kw_only=True)
class SystemEvent(BaseEvent): ...


@dataclass(frozen=True, kw_only=True)
class UserEvent(BaseEvent):
    user: UserDto
