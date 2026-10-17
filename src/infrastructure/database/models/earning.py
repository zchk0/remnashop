from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseSql
from .timestamp import TimestampMixin


class ChannelTask(BaseSql, TimestampMixin):
    __tablename__ = "channel_tasks"
    __table_args__ = (
        CheckConstraint("days >= 0 AND discount BETWEEN 0 AND 100", name="valid_task_reward"),
        CheckConstraint("max_claims IS NULL OR max_claims > 0", name="valid_task_capacity"),
        CheckConstraint("trial_days IS NULL OR trial_days > 0", name="valid_task_trial_days"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    channel_id: Mapped[int] = mapped_column(BigInteger)
    channel_url: Mapped[str]
    days: Mapped[int]
    reset_traffic: Mapped[bool]
    discount: Mapped[int]
    max_claims: Mapped[int | None]
    active: Mapped[bool]
    deleted: Mapped[bool]
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id", ondelete="RESTRICT"))
    trial_plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id", ondelete="RESTRICT"))
    trial_days: Mapped[int | None]


class ChannelClaim(BaseSql, TimestampMixin):
    __tablename__ = "channel_claims"
    __table_args__ = (
        UniqueConstraint("task_id", "user_id", name="uq_channel_claim_user"),
        Index(
            "ix_channel_claims_completed_at",
            "completed_at",
            postgresql_where=text("status = 'completed'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("channel_tasks.id", ondelete="RESTRICT"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str]
    subscription_applied: Mapped[bool]
    reset_started: Mapped[bool]
    reset_applied: Mapped[bool]
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
