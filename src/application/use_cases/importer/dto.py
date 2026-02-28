from dataclasses import dataclass
from datetime import datetime

from src.core.enums import SubscriptionStatus


@dataclass(frozen=True)
class ExportedUserDto:
    username: str
    telegram_id: int
    status: SubscriptionStatus
    expire_at: datetime
    traffic_limit_bytes: int
    hwid_device_limit: int
    tag: str
