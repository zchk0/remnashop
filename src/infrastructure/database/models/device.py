from typing import Optional

from sqlalchemy import BigInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseSql
from .timestamp import TimestampMixin


class LinkedDevice(BaseSql, TimestampMixin):
    __tablename__ = "linked_devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, index=True)

    panel_user_uuid: Mapped[Optional[str]] = mapped_column(Text)
    short_uuid: Mapped[Optional[str]] = mapped_column(Text)
    anon_traffic_bytes: Mapped[int] = mapped_column(BigInteger, default=0)

    device_name: Mapped[Optional[str]] = mapped_column(String(256))
    device_type: Mapped[Optional[str]] = mapped_column(String(32))
    platform: Mapped[Optional[str]] = mapped_column(String(64))
