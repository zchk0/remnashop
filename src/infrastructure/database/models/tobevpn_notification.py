from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, Index, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseSql


class ToBeVpnNotification(BaseSql):
    __tablename__ = "tobevpn_notifications"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(100))
    body: Mapped[str] = mapped_column(Text)
    action: Mapped[str | None] = mapped_column(String(16))
    is_public: Mapped[bool]
    published_at: Mapped[datetime] = mapped_column(index=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)


class ToBeVpnNotificationRecipient(BaseSql):
    __tablename__ = "tobevpn_notification_recipients"
    __table_args__ = (
        Index("ix_tobevpn_recipient_user_notification", "user_id", "notification_id"),
    )

    notification_id: Mapped[UUID] = mapped_column(
        ForeignKey("tobevpn_notifications.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )


class ToBeVpnNotificationRead(BaseSql):
    __tablename__ = "tobevpn_notification_reads"

    notification_id: Mapped[UUID] = mapped_column(
        ForeignKey("tobevpn_notifications.id", ondelete="CASCADE"), primary_key=True
    )
    reader: Mapped[str] = mapped_column(String(40), primary_key=True)
    read_at: Mapped[datetime]


class ToBeVpnPushDelivery(BaseSql):
    __tablename__ = "tobevpn_push_deliveries"
    __table_args__ = (
        UniqueConstraint("notification_id", "device_id"),
        Index("ix_tobevpn_push_deliveries_due", "available_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    notification_id: Mapped[UUID] = mapped_column(
        ForeignKey("tobevpn_notifications.id", ondelete="CASCADE")
    )
    device_id: Mapped[str] = mapped_column(String(128))
    device_session_id: Mapped[UUID]
    available_at: Mapped[datetime]
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
