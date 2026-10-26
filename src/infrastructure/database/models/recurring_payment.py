from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseSql
from .timestamp import TimestampMixin


class RecurringPayment(BaseSql, TimestampMixin):
    __tablename__ = "recurring_payments"
    __table_args__ = (
        Index(
            "uq_recurring_payments_open_user",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('Pending', 'Active', 'PastDue')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="Pending")
    email: Mapped[str | None] = mapped_column(String(255))
    payment_url: Mapped[str]
    plan_snapshot: Mapped[dict[str, Any]]
    pricing: Mapped[dict[str, Any]]
    purchase_type: Mapped[str] = mapped_column(String(16))
    display_name: Mapped[str]
    next_charge_at: Mapped[datetime | None]


class RecurringPaymentEvent(BaseSql, TimestampMixin):
    """Durable callback inbox and replayable entitlement target for each charge."""

    __tablename__ = "recurring_payment_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    subscription_id: Mapped[UUID] = mapped_column(index=True)
    payload: Mapped[dict[str, Any]]
    target: Mapped[dict[str, Any] | None]
    processed_at: Mapped[datetime | None] = mapped_column(index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None]
