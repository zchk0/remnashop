from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from src.core.enums import (
    PromocodeActivationStatus,
    PromocodeAvailability,
    PromocodeRemoteAction,
    PromocodeRewardType,
)

from .base import BaseDto, TimestampMixin, TrackableMixin


@dataclass(kw_only=True)
class PromocodeDto(BaseDto, TrackableMixin, TimestampMixin):
    code: str
    is_active: bool
    reward_type: PromocodeRewardType
    reward: Optional[int] = None
    plan_snapshot: Optional[dict[str, Any]] = None
    availability: PromocodeAvailability = PromocodeAvailability.ALL
    expires_at: Optional[datetime] = None
    max_activations: Optional[int] = None
    is_reusable: bool = False


@dataclass(kw_only=True)
class PromocodeActivationDto(BaseDto):
    promocode_id: int
    user_id: int
    activated_at: datetime
    request_id: Optional[UUID] = None
    status: PromocodeActivationStatus = PromocodeActivationStatus.APPLIED
    remote_action: PromocodeRemoteAction = PromocodeRemoteAction.NONE
    target_remna_id: Optional[UUID] = None
    reset_traffic: bool = False
    last_error: Optional[str] = None


@dataclass(kw_only=True)
class PromocodeActivationDetailDto:
    activation_id: int
    promocode_id: int
    code: str
    reward_type: PromocodeRewardType
    reward: Optional[int]
    plan_snapshot: Optional[dict[str, Any]]
    activated_at: datetime
