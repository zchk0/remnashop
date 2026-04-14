from typing import Optional

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseSql
from .timestamp import TimestampMixin


class TvPairingCode(BaseSql, TimestampMixin):
    __tablename__ = "tv_pairing_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    device_id: Mapped[str] = mapped_column(String(128), index=True)

    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger)
