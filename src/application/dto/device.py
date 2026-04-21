from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .base import BaseDto, TimestampMixin


@dataclass(kw_only=True)
class LinkedDeviceDto(BaseDto, TimestampMixin):
    device_id: str
    telegram_id: Optional[int] = None
    panel_user_uuid: Optional[str] = None
    short_uuid: Optional[str] = None
    anon_traffic_bytes: int = 0
    device_name: Optional[str] = None
    device_type: Optional[str] = None
    platform: Optional[str] = None


@dataclass(kw_only=True)
class AuthTokenDto(BaseDto, TimestampMixin):
    token: str
    device_id: str
    status: str = "pending"
    telegram_id: Optional[int] = None
    short_uuid: Optional[str] = None
    panel_user_uuid: Optional[str] = None


@dataclass(kw_only=True)
class DeviceSessionDto(BaseDto, TimestampMixin):
    device_id: str
    access_token_hash: str
    refresh_token_hash: str
    access_expires_at: datetime
    refresh_expires_at: datetime
    platform: Optional[str] = None
    integrity_token_hash: Optional[str] = None
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


@dataclass(kw_only=True)
class TvPairingCodeDto(BaseDto, TimestampMixin):
    code: str
    device_id: str
    status: str = "pending"
    telegram_id: Optional[int] = None
