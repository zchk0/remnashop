from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.enums import (
    PromocodeActivationStatus,
    PromocodeAvailability,
    PromocodeRemoteAction,
    PromocodeRewardType,
)

from .base import BaseSql
from .timestamp import TimestampMixin


class Promocode(BaseSql, TimestampMixin):
    __tablename__ = "promocodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    reward_type: Mapped[PromocodeRewardType]
    reward: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    plan_snapshot: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    availability: Mapped[PromocodeAvailability]

    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    max_activations: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_reusable: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))

    activations: Mapped[list["PromocodeActivation"]] = relationship(
        back_populates="promocode",
        lazy="noload",
        passive_deletes=True,
    )


class PromocodeActivation(BaseSql):
    __tablename__ = "promocode_activations"
    __table_args__ = (
        Index(
            "ix_promocode_activations_request_id",
            "request_id",
            unique=True,
            postgresql_where=text("request_id IS NOT NULL"),
        ),
        Index(
            "uq_promocode_activations_pending_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    promocode_id: Mapped[int] = mapped_column(
        ForeignKey("promocodes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("timezone('UTC', now())"),
    )
    code_snapshot: Mapped[str]
    reward_type_snapshot: Mapped[PromocodeRewardType]
    reward_snapshot: Mapped[Optional[int]] = mapped_column(Integer)
    plan_snapshot: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    request_id: Mapped[Optional[UUID]]
    status: Mapped[PromocodeActivationStatus] = mapped_column(
        Enum(PromocodeActivationStatus, native_enum=False, length=16),
        nullable=False,
        default=PromocodeActivationStatus.APPLIED,
        server_default=PromocodeActivationStatus.APPLIED.value,
        index=True,
    )
    remote_action: Mapped[PromocodeRemoteAction] = mapped_column(
        Enum(PromocodeRemoteAction, native_enum=False, length=32),
        nullable=False,
        default=PromocodeRemoteAction.NONE,
        server_default=PromocodeRemoteAction.NONE.value,
    )
    target_remna_id: Mapped[Optional[UUID]] = mapped_column(index=True)
    reset_traffic: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text)

    promocode: Mapped["Promocode"] = relationship(back_populates="activations")
