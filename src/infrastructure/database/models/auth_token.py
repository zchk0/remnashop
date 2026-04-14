from typing import Optional

from sqlalchemy import BigInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseSql
from .timestamp import TimestampMixin


class AuthToken(BaseSql, TimestampMixin):
    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    device_id: Mapped[str] = mapped_column(String(128), index=True)

    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    short_uuid: Mapped[Optional[str]] = mapped_column(Text)
    panel_user_uuid: Mapped[Optional[str]] = mapped_column(Text)
