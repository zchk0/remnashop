from dataclasses import dataclass, field
from typing import Any

from aiogram.enums import ButtonStyle

from src.application.dto.base import TrackableMixin
from src.application.dto.subscription import SubscriptionDto
from src.application.dto.user import UserDto


@dataclass(kw_only=True)
class EarningSettingsDto(TrackableMixin):
    enabled: bool = False
    audience: str = "admins"
    allowed_telegram_ids: list[int] = field(default_factory=list)
    button_text: str = "🎁 Заработай бесплатные дни"
    button_color: ButtonStyle | None = ButtonStyle.SUCCESS
    subscriber_price: str = "Уточните в поддержке"

    def allows(self, user: UserDto) -> bool:
        if not self.enabled or user.is_blocked or user.telegram_id is None:
            return False
        return (
            self.audience == "all"
            or (self.audience == "admins" and user.is_privileged)
            or (self.audience == "selected" and user.telegram_id in self.allowed_telegram_ids)
        )


@dataclass(kw_only=True)
class ChannelTaskDto:
    id: int = 0
    title: str = "Новый канал"
    channel_id: int = 0
    channel_url: str = ""
    days: int = 1
    reset_traffic: bool = False
    discount: int = 0
    max_claims: int | None = None
    active: bool = False
    deleted: bool = False
    # Used for users without a subscription, and optionally to replace a trial.
    plan_id: int | None = None
    trial_plan_id: int | None = None
    trial_days: int | None = None
    claims_count: int = 0
    completed_claims_count: int = 0

    @property
    def is_completed(self) -> bool:
        return self.max_claims is not None and self.completed_claims_count >= self.max_claims

    def reward_days(self, subscription: SubscriptionDto | None) -> int:
        if subscription and subscription.is_trial and self.trial_plan_id:
            return self.trial_days or self.days
        return self.days

    def eligible(self, subscription: SubscriptionDto | None) -> bool:
        if not (self.days or self.reset_traffic or self.discount):
            return False
        if subscription is None:
            return not (self.days or self.reset_traffic) or bool(self.days and self.plan_id)
        return True


@dataclass(kw_only=True)
class ChannelClaimDto:
    task_id: int
    user_id: int
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    subscription_applied: bool = False
    reset_started: bool = False
    reset_applied: bool = False


@dataclass(frozen=True, kw_only=True)
class EarningStatisticsDto:
    daily: int = 0
    weekly: int = 0
    monthly: int = 0
    total: int = 0
    active_tasks: int = 0
    completed_tasks: int = 0
