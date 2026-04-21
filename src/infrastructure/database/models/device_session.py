from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseSql
from .timestamp import TimestampMixin


class DeviceSession(BaseSql, TimestampMixin):
    __tablename__ = "device_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    access_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    access_expires_at: Mapped[datetime]
    refresh_expires_at: Mapped[datetime]
    platform: Mapped[Optional[str]] = mapped_column(String(64))
    integrity_token_hash: Mapped[Optional[str]] = mapped_column(Text)
    last_used_at: Mapped[Optional[datetime]]
    revoked_at: Mapped[Optional[datetime]]
