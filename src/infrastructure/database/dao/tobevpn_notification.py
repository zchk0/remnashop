from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import (
    SQLColumnExpression,
    String,
    and_,
    delete,
    exists,
    func,
    literal,
    not_,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from src.core.enums import BroadcastAudience, SubscriptionStatus
from src.infrastructure.database.models import (
    DeviceSession,
    LinkedDevice,
    Subscription,
    ToBeVpnNotification,
    ToBeVpnNotificationRead,
    ToBeVpnNotificationRecipient,
    ToBeVpnPushDelivery,
    User,
)

NOTIFICATION_LIFETIME = timedelta(days=30)
PUSH_LIFETIME = timedelta(days=1)
PUSH_LEASE = timedelta(minutes=2)


@dataclass(frozen=True)
class NotificationDraft:
    id: UUID
    title: str
    body: str
    audience: BroadcastAudience
    plan_id: int | None
    action: str | None
    guests_only: bool = False


@dataclass(frozen=True)
class NotificationReader:
    key: str
    user_id: int | None
    is_guest: bool


@dataclass(frozen=True)
class PushDelivery:
    id: int
    attempts: int
    device_id: str
    session_id: UUID
    notification_id: UUID
    title: str
    body: str
    push_expires_at: datetime
    token: str = field(repr=False)


class ToBeVpnNotificationDao:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def publish(self, draft: NotificationDraft, *, queue_push: bool) -> bool:
        now = datetime.now(UTC)
        # Older servers hide nonpublic announcements with no account recipients.
        is_public = draft.audience == BroadcastAudience.ALL and not draft.guests_only
        published_id = await self.session.scalar(
            insert(ToBeVpnNotification)
            .values(
                id=draft.id,
                title=draft.title,
                body=draft.body,
                action=draft.action,
                is_public=is_public,
                guests_only=draft.guests_only,
                published_at=now,
                expires_at=now + NOTIFICATION_LIFETIME,
            )
            .on_conflict_do_nothing()
            .returning(ToBeVpnNotification.id)
        )
        if published_id is None:
            return False

        if not (is_public or draft.guests_only):
            await self.session.execute(
                insert(ToBeVpnNotificationRecipient).from_select(
                    ["notification_id", "user_id"], self._recipients(draft)
                )
            )

        if queue_push:
            targets = (
                select(
                    literal(draft.id),
                    DeviceSession.device_id,
                    DeviceSession.session_id,
                    literal(now),
                )
                .join(LinkedDevice, LinkedDevice.device_id == DeviceSession.device_id)
                .outerjoin(User, User.telegram_id == LinkedDevice.telegram_id)
                .where(
                    self._active_android_session(now),
                    self._eligible_for_push(
                        literal(is_public), literal(draft.guests_only), literal(draft.id)
                    ),
                )
            )
            await self.session.execute(
                insert(ToBeVpnPushDelivery).from_select(
                    ["notification_id", "device_id", "device_session_id", "available_at"],
                    targets,
                )
            )
        return True

    async def list_published(self) -> list[tuple[UUID, str, datetime]]:
        stmt = (
            select(
                ToBeVpnNotification.id,
                ToBeVpnNotification.title,
                ToBeVpnNotification.published_at,
            )
            .where(ToBeVpnNotification.expires_at > func.now())
            .order_by(ToBeVpnNotification.published_at.desc(), ToBeVpnNotification.id.desc())
        )
        return list((await self.session.execute(stmt)).tuples().all())

    async def get_publication(
        self, notification_id: UUID
    ) -> tuple[ToBeVpnNotification, int, int] | None:
        read_count = (
            select(func.count())
            .select_from(ToBeVpnNotificationRead)
            .where(ToBeVpnNotificationRead.notification_id == notification_id)
            .scalar_subquery()
        )
        recipient_count = (
            select(func.count())
            .select_from(ToBeVpnNotificationRecipient)
            .where(ToBeVpnNotificationRecipient.notification_id == notification_id)
            .scalar_subquery()
        )
        stmt = select(ToBeVpnNotification, read_count, recipient_count).where(
            ToBeVpnNotification.id == notification_id,
            ToBeVpnNotification.expires_at > func.now(),
        )
        return (await self.session.execute(stmt)).tuples().one_or_none()

    async def delete_publication(self, notification_id: UUID) -> None:
        await self.session.execute(
            delete(ToBeVpnNotification).where(ToBeVpnNotification.id == notification_id)
        )

    def _recipients(self, draft: NotificationDraft) -> Select[tuple[UUID, int]]:
        users = select(literal(draft.id), User.id).where(
            User.is_blocked.is_(False),
            exists().where(
                LinkedDevice.telegram_id == User.telegram_id,
                or_(
                    LinkedDevice.platform.in_(("android", "desktop", "windows", "linux", "macos")),
                    LinkedDevice.device_type == "desktop",
                ),
            ),
        )
        if draft.audience == BroadcastAudience.UNSUBSCRIBED:
            return users.where(User.current_subscription_id.is_(None))

        users = users.join(Subscription, User.current_subscription_id == Subscription.id)
        if draft.audience == BroadcastAudience.TRIAL:
            return users.where(Subscription.is_trial.is_(True))
        if draft.audience == BroadcastAudience.EXPIRED:
            return users.where(Subscription.status == SubscriptionStatus.EXPIRED)

        users = users.where(Subscription.status == SubscriptionStatus.ACTIVE)
        if draft.audience == BroadcastAudience.PLAN:
            return users.where(Subscription.plan_snapshot["id"].as_integer() == draft.plan_id)
        return users

    def _visible(
        self, reader: NotificationReader
    ) -> Select[tuple[ToBeVpnNotification, datetime | None]]:
        visible = or_(
            ToBeVpnNotification.is_public.is_(True),
            and_(ToBeVpnNotification.guests_only.is_(True), reader.is_guest),
        )
        if reader.user_id is not None:
            visible = or_(
                visible,
                and_(
                    ToBeVpnNotification.is_public.is_(False),
                    ToBeVpnNotification.guests_only.is_(False),
                    exists().where(
                        ToBeVpnNotificationRecipient.notification_id == ToBeVpnNotification.id,
                        ToBeVpnNotificationRecipient.user_id == reader.user_id,
                    ),
                ),
            )
        return (
            select(
                ToBeVpnNotification,
                cast("SQLColumnExpression[datetime | None]", ToBeVpnNotificationRead.read_at),
            )
            .outerjoin(
                ToBeVpnNotificationRead,
                and_(
                    ToBeVpnNotificationRead.notification_id == ToBeVpnNotification.id,
                    ToBeVpnNotificationRead.reader == reader.key,
                ),
            )
            .where(visible, ToBeVpnNotification.expires_at > func.now())
        )

    async def list_visible(
        self, reader: NotificationReader
    ) -> list[tuple[UUID, str, str, datetime, datetime | None]]:
        stmt = (
            self._visible(reader)
            .with_only_columns(
                ToBeVpnNotification.id,
                ToBeVpnNotification.title,
                func.left(ToBeVpnNotification.body, 180, type_=String),
                ToBeVpnNotification.published_at,
                cast("SQLColumnExpression[datetime | None]", ToBeVpnNotificationRead.read_at),
            )
            .order_by(ToBeVpnNotification.published_at.desc(), ToBeVpnNotification.id.desc())
            .limit(50)
        )
        return list((await self.session.execute(stmt)).tuples().all())

    async def get_visible(
        self, notification_id: UUID, reader: NotificationReader
    ) -> tuple[ToBeVpnNotification, datetime | None] | None:
        stmt = self._visible(reader).where(ToBeVpnNotification.id == notification_id)
        return (await self.session.execute(stmt)).tuples().one_or_none()

    async def mark_read(self, notification_id: UUID, reader: NotificationReader) -> datetime | None:
        # Keep the publication available until the read receipt is saved.
        stmt = (
            self._visible(reader)
            .where(ToBeVpnNotification.id == notification_id)
            .with_for_update(read=True, key_share=True, of=ToBeVpnNotification)
        )
        visible = (await self.session.execute(stmt)).tuples().one_or_none()
        if visible is None:
            return None
        if visible[1] is not None:
            return visible[1]
        stmt = (
            insert(ToBeVpnNotificationRead)
            .values(notification_id=notification_id, reader=reader.key, read_at=datetime.now(UTC))
            .on_conflict_do_nothing()
            .returning(ToBeVpnNotificationRead.read_at)
        )
        return await self.session.scalar(stmt) or await self.session.scalar(
            select(ToBeVpnNotificationRead.read_at).where(
                ToBeVpnNotificationRead.notification_id == notification_id,
                ToBeVpnNotificationRead.reader == reader.key,
            )
        )

    async def register_push(self, device_id: str, session_id: UUID, token: str) -> bool:
        # Transfer a Firebase token if the installation was restored with a new device id.
        await self.session.execute(
            update(DeviceSession)
            .where(DeviceSession.push_token == token, DeviceSession.device_id != device_id)
            .values(push_token=None)
        )
        return (
            await self.session.scalar(
                update(DeviceSession)
                .where(
                    DeviceSession.device_id == device_id,
                    DeviceSession.session_id == session_id,
                    DeviceSession.platform == "android",
                    DeviceSession.revoked_at.is_(None),
                )
                .values(push_token=token)
                .returning(DeviceSession.id)
            )
        ) is not None

    @staticmethod
    def _active_android_session(now: datetime) -> ColumnElement[bool]:
        return and_(
            DeviceSession.platform == "android",
            DeviceSession.revoked_at.is_(None),
            DeviceSession.refresh_expires_at > now,
            DeviceSession.push_token.is_not(None),
        )

    @staticmethod
    def _eligible_for_push(
        is_public: SQLColumnExpression[bool],
        guests_only: SQLColumnExpression[bool],
        notification_id: SQLColumnExpression[UUID],
    ) -> ColumnElement[bool]:
        return and_(
            User.is_blocked.is_not(True),
            or_(
                is_public,
                and_(guests_only, LinkedDevice.telegram_id.is_(None)),
                and_(
                    not_(is_public),
                    not_(guests_only),
                    DeviceSession.verified_telegram_id == LinkedDevice.telegram_id,
                    exists().where(
                        ToBeVpnNotificationRecipient.notification_id == notification_id,
                        ToBeVpnNotificationRecipient.user_id == User.id,
                    ),
                ),
            ),
        )

    async def claim_push(self, limit: int) -> tuple[list[PushDelivery], list[int], datetime]:
        now = datetime.now(UTC)
        lease_until = now + PUSH_LEASE
        due = (
            select(ToBeVpnPushDelivery.id)
            .where(ToBeVpnPushDelivery.available_at <= now)
            .order_by(ToBeVpnPushDelivery.available_at, ToBeVpnPushDelivery.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        claimed = list(
            await self.session.scalars(
                update(ToBeVpnPushDelivery)
                .where(ToBeVpnPushDelivery.id.in_(due))
                .values(
                    available_at=lease_until,
                    attempts=ToBeVpnPushDelivery.attempts + 1,
                )
                .returning(ToBeVpnPushDelivery.id)
            )
        )
        if not claimed:
            return [], [], lease_until

        stmt = (
            select(
                ToBeVpnPushDelivery.id,
                ToBeVpnPushDelivery.attempts,
                ToBeVpnPushDelivery.device_id,
                ToBeVpnPushDelivery.device_session_id,
                ToBeVpnNotification.id,
                ToBeVpnNotification.title,
                ToBeVpnNotification.body,
                ToBeVpnNotification.published_at,
                DeviceSession.push_token,
            )
            .select_from(ToBeVpnPushDelivery)
            .join(
                ToBeVpnNotification, ToBeVpnNotification.id == ToBeVpnPushDelivery.notification_id
            )
            .join(
                DeviceSession,
                and_(
                    DeviceSession.device_id == ToBeVpnPushDelivery.device_id,
                    DeviceSession.session_id == ToBeVpnPushDelivery.device_session_id,
                ),
            )
            .join(LinkedDevice, LinkedDevice.device_id == DeviceSession.device_id)
            .outerjoin(User, User.telegram_id == LinkedDevice.telegram_id)
            .where(
                ToBeVpnPushDelivery.id.in_(claimed),
                ToBeVpnNotification.published_at > now - PUSH_LIFETIME,
                self._active_android_session(now),
                self._eligible_for_push(
                    ToBeVpnNotification.is_public,
                    ToBeVpnNotification.guests_only,
                    ToBeVpnNotification.id,
                ),
            )
        )
        valid: list[PushDelivery] = []
        for row in (await self.session.execute(stmt)).tuples():
            (
                delivery_id,
                attempts,
                device_id,
                session_id,
                notice_id,
                title,
                body,
                published,
                token,
            ) = row
            if token is not None:
                valid.append(
                    PushDelivery(
                        delivery_id,
                        attempts,
                        device_id,
                        session_id,
                        notice_id,
                        title,
                        body,
                        published + PUSH_LIFETIME,
                        token,
                    )
                )
        return valid, list(set(claimed).difference(item.id for item in valid)), lease_until

    async def finish_push(self, delivery_ids: list[int], lease_until: datetime) -> None:
        if delivery_ids:
            await self.session.execute(
                delete(ToBeVpnPushDelivery).where(
                    ToBeVpnPushDelivery.id.in_(delivery_ids),
                    ToBeVpnPushDelivery.available_at == lease_until,
                )
            )

    async def retry_push(self, delivery_id: int, delay: timedelta, lease_until: datetime) -> None:
        await self.session.execute(
            update(ToBeVpnPushDelivery)
            .where(
                ToBeVpnPushDelivery.id == delivery_id,
                ToBeVpnPushDelivery.available_at == lease_until,
            )
            .values(available_at=datetime.now(UTC) + delay)
        )

    async def remove_invalid_push_token(self, delivery: PushDelivery) -> None:
        await self.session.execute(
            update(DeviceSession)
            .where(
                DeviceSession.device_id == delivery.device_id,
                DeviceSession.session_id == delivery.session_id,
                DeviceSession.push_token == delivery.token,
            )
            .values(push_token=None)
        )

    async def delete_expired(self) -> None:
        await self.session.execute(
            delete(ToBeVpnNotification).where(ToBeVpnNotification.expires_at <= func.now())
        )
