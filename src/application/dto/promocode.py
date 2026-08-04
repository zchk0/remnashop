from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from src.core.enums import (
    PromocodeActivationEventStatus,
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
    deleted_at: Optional[datetime] = None
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
    code_snapshot: str
    reward_type_snapshot: PromocodeRewardType
    reward_snapshot: Optional[int] = None
    plan_snapshot: Optional[dict[str, Any]] = None
    request_id: Optional[UUID] = None
    status: PromocodeActivationStatus = PromocodeActivationStatus.APPLIED
    remote_action: PromocodeRemoteAction = PromocodeRemoteAction.NONE
    target_remna_id: Optional[UUID] = None
    reset_traffic: bool = False
    last_error: Optional[str] = None
    attempt_count: int = 0
    next_retry_at: Optional[datetime] = None
    event_status: Optional[PromocodeActivationEventStatus] = None
    event_attempt_count: int = 0
    event_next_retry_at: Optional[datetime] = None
    event_last_error: Optional[str] = None
    event_sent_at: Optional[datetime] = None


@dataclass(kw_only=True)
class PromocodeActivationDetailDto:
    activation_id: int
    promocode_id: int
    code: str
    reward_type: PromocodeRewardType
    reward: Optional[int]
    plan_snapshot: Optional[dict[str, Any]]
    activated_at: datetime
