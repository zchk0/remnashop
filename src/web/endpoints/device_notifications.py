from datetime import datetime
from typing import Annotated
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.exc import IntegrityError

from src.application.common.dao import UserDao
from src.application.common.uow import UnitOfWork
from src.infrastructure.database.dao.tobevpn_notification import ToBeVpnNotificationDao
from src.infrastructure.database.models import ToBeVpnNotification

from .devices import DeviceAuthContext, get_device_auth_context

router = APIRouter(prefix="/api/device", tags=["ToBeVPN notifications"])
DeviceAuth = Annotated[DeviceAuthContext, Depends(get_device_auth_context)]


class NotificationItem(BaseModel):
    id: UUID
    title: str
    preview: str
    published_at: datetime
    read_at: datetime | None

    @classmethod
    def from_record(
        cls, record: ToBeVpnNotification, read_at: datetime | None
    ) -> "NotificationItem":
        return cls(
            id=record.id,
            title=record.title,
            preview=record.body[:180],
            published_at=record.published_at,
            read_at=read_at,
        )


class NotificationList(BaseModel):
    success: bool = True
    data: list[NotificationItem]


class NotificationDetails(NotificationItem):
    body: str
    action: str | None


class NotificationDetailResponse(BaseModel):
    success: bool = True
    data: NotificationDetails


class ReadReceipt(BaseModel):
    read_at: datetime


class NotificationReadResponse(BaseModel):
    success: bool = True
    data: ReadReceipt


class PushRegistration(BaseModel):
    token: SecretStr = Field(min_length=1, max_length=512)


@inject
async def notification_reader(
    auth: DeviceAuth,
    user_dao: FromDishka[UserDao],
) -> tuple[int | None, str]:
    if auth.session_id is None:
        raise HTTPException(status_code=401, detail="Missing device session")

    if auth.telegram_id is not None and auth.verified_telegram_id == auth.telegram_id:
        user = await user_dao.get_by_telegram_id(auth.telegram_id)
        if user is not None:
            if user.is_blocked:
                raise HTTPException(status_code=403, detail="User is blocked")
            return user.id, f"u:{user.id}"

    return None, f"s:{auth.session_id}"


Reader = Annotated[tuple[int | None, str], Depends(notification_reader)]


@router.get("/notifications")
@inject
async def list_notifications(
    reader: Reader,
    notifications: FromDishka[ToBeVpnNotificationDao],
    response: Response,
) -> NotificationList:
    response.headers["Cache-Control"] = "private, no-store"
    return NotificationList(
        data=[
            NotificationItem(
                id=item_id, title=title, preview=preview, published_at=published_at, read_at=read_at
            )
            for item_id, title, preview, published_at, read_at in await notifications.list_visible(
                *reader
            )
        ]
    )


@router.get("/notifications/{notification_id}")
@inject
async def get_notification(
    notification_id: UUID,
    reader: Reader,
    notifications: FromDishka[ToBeVpnNotificationDao],
    response: Response,
) -> NotificationDetailResponse:
    response.headers["Cache-Control"] = "private, no-store"
    result = await notifications.get_visible(notification_id, *reader)
    if result is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    item, read_at = result
    return NotificationDetailResponse(
        data=NotificationDetails(
            **NotificationItem.from_record(item, read_at).model_dump(),
            body=item.body,
            action=item.action,
        )
    )


@router.post("/notifications/{notification_id}/read")
@inject
async def read_notification(
    notification_id: UUID,
    reader: Reader,
    notifications: FromDishka[ToBeVpnNotificationDao],
    uow: FromDishka[UnitOfWork],
) -> NotificationReadResponse:
    read_at = await notifications.mark_read(notification_id, *reader)
    if read_at is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    await uow.commit()
    return NotificationReadResponse(data=ReadReceipt(read_at=read_at))


@router.put("/push-registration", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def register_push(
    request: PushRegistration,
    auth: DeviceAuth,
    notifications: FromDishka[ToBeVpnNotificationDao],
    uow: FromDishka[UnitOfWork],
) -> None:
    if auth.platform != "android" or auth.device_id is None or auth.session_id is None:
        raise HTTPException(status_code=403, detail="Android device session required")
    token = request.token.get_secret_value()
    if not token.isascii() or not token.isprintable() or any(char.isspace() for char in token):
        raise HTTPException(status_code=422, detail="Invalid Firebase registration")
    try:
        registered = await notifications.register_push(auth.device_id, auth.session_id, token)
    except IntegrityError:
        await uow.rollback()
        raise HTTPException(status_code=409, detail="Firebase registration changed") from None
    if not registered:
        await uow.rollback()
        raise HTTPException(status_code=401, detail="Device session changed")
    await uow.commit()
