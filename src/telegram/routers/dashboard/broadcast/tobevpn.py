import html
from typing import Any
from uuid import UUID, uuid4

from aiogram.enums import ContentType
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button as DialogButton
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger
from magic_filter import F

from src.application.common import TranslatorRunner
from src.application.common.dao import PlanDao
from src.application.common.policy import Permission, PermissionPolicy
from src.application.common.uow import UnitOfWork
from src.core.config import AppConfig
from src.core.constants import USER_KEY
from src.core.enums import BannerName, BroadcastAudience
from src.infrastructure.database.dao.tobevpn_notification import (
    NotificationDraft,
    ToBeVpnNotificationDao,
)
from src.telegram.states import DashboardBroadcast
from src.telegram.widgets import Banner, I18nFormat, IgnoreUpdate
from src.telegram.widgets.kbd import Button, Column, Row, Select, SwitchTo

from .getters import plans_getter


@inject
async def open_tobevpn(
    callback: CallbackQuery,
    widget: DialogButton,
    manager: DialogManager,
    config: FromDishka[AppConfig],
    i18n: FromDishka[TranslatorRunner],
) -> None:
    if not config.tobevpn.is_enabled:
        await callback.answer(i18n.get("msg-tobevpn-broadcast-disabled"), show_alert=True)
        return
    manager.dialog_data["tobevpn"] = {}
    await manager.switch_to(DashboardBroadcast.TOBEVPN_AUDIENCE)


async def select_audience(
    callback: CallbackQuery, widget: DialogButton, manager: DialogManager
) -> None:
    if widget.widget_id is None:
        return
    audience = BroadcastAudience(widget.widget_id)
    draft = manager.dialog_data["tobevpn"]
    draft.update(audience=audience.value, plan_id=None, plan_name="")
    await manager.switch_to(
        DashboardBroadcast.TOBEVPN_PLAN
        if audience == BroadcastAudience.PLAN
        else DashboardBroadcast.TOBEVPN_CONTENT
    )


@inject
async def select_plan(
    callback: CallbackQuery,
    widget: Any,
    manager: DialogManager,
    plan_id: int,
    plan_dao: FromDishka[PlanDao],
    i18n: FromDishka[TranslatorRunner],
) -> None:
    plan = await plan_dao.get_by_id(plan_id)
    if plan is None or plan.is_trial:
        return
    manager.dialog_data["tobevpn"].update(plan_id=plan_id, plan_name=i18n.get(plan.name))
    await manager.switch_to(DashboardBroadcast.TOBEVPN_CONTENT)


@inject
async def enter_content(
    message: Message,
    widget: MessageInput,
    manager: DialogManager,
    i18n: FromDishka[TranslatorRunner],
) -> None:
    title, _, body = (message.text or "").strip().partition("\n")
    title, body = title.strip(), body.strip()
    if not 1 <= len(title) <= 100 or not 1 <= len(body) <= 3000:
        await message.answer(i18n.get("msg-tobevpn-broadcast-invalid"))
        return
    manager.dialog_data["tobevpn"].update(id=str(uuid4()), title=title, body=body)
    await manager.switch_to(DashboardBroadcast.TOBEVPN_PREVIEW)


async def toggle_plans(
    callback: CallbackQuery, widget: DialogButton, manager: DialogManager
) -> None:
    draft = manager.dialog_data["tobevpn"]
    draft["action"] = None if draft.get("action") == "plans" else "plans"


@inject
async def tobevpn_preview(
    dialog_manager: DialogManager, config: FromDishka[AppConfig], **kwargs: Any
) -> dict[str, Any]:
    draft = dialog_manager.dialog_data["tobevpn"]
    return {
        "audience_type": draft["audience"],
        "is_public": draft["audience"] == BroadcastAudience.ALL,
        "plan_name": f" — {html.escape(draft['plan_name'])}" if draft["plan_name"] else "",
        "title": html.escape(draft["title"]),
        "body": html.escape(draft["body"]),
        "open_plans": draft.get("action") == "plans",
        "fcm_enabled": config.tobevpn.fcm_service_account_json is not None,
    }


@inject
async def publish_tobevpn(
    callback: CallbackQuery,
    widget: DialogButton,
    manager: DialogManager,
    config: FromDishka[AppConfig],
    i18n: FromDishka[TranslatorRunner],
    notifications: FromDishka[ToBeVpnNotificationDao],
    uow: FromDishka[UnitOfWork],
) -> None:
    user = manager.middleware_data[USER_KEY]
    if not PermissionPolicy.has_permission(user, Permission.BROADCAST):
        return
    if not config.tobevpn.is_enabled:
        await callback.answer(i18n.get("msg-tobevpn-broadcast-disabled"), show_alert=True)
        return
    values = manager.dialog_data["tobevpn"]
    draft = NotificationDraft(
        id=UUID(values["id"]),
        title=values["title"],
        body=values["body"],
        audience=BroadcastAudience(values["audience"]),
        plan_id=values.get("plan_id"),
        action=values.get("action"),
    )
    queue_push = config.tobevpn.fcm_service_account_json is not None
    is_new = await notifications.publish(draft, queue_push=queue_push)
    await uow.commit()
    if is_new and queue_push:
        await kick_push_worker()
    await manager.switch_to(DashboardBroadcast.TOBEVPN_PUBLISHED)


async def kick_push_worker() -> None:
    from src.infrastructure.taskiq.tasks.tobevpn_notification import (  # noqa: PLC0415
        send_tobevpn_pushes,
    )

    try:
        # Dishka supplies the dependencies in the worker.
        await send_tobevpn_pushes.kiq()  # type: ignore[call-overload]
    except Exception:
        logger.warning("Could not start ToBeVPN push worker immediately; scheduled run will retry")


def audience_button(audience: BroadcastAudience, label: str) -> Button:
    return Button(I18nFormat(label), id=audience.value, on_click=select_audience)


tobevpn_audience = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-tobevpn-broadcast-audience"),
    Row(
        audience_button(BroadcastAudience.ALL, "btn-tobevpn-broadcast.all"),
        audience_button(BroadcastAudience.PLAN, "btn-broadcast.plan"),
    ),
    Row(
        audience_button(BroadcastAudience.SUBSCRIBED, "btn-broadcast.subscribed"),
        audience_button(BroadcastAudience.UNSUBSCRIBED, "btn-broadcast.unsubscribed"),
    ),
    Row(
        audience_button(BroadcastAudience.EXPIRED, "btn-broadcast.expired"),
        audience_button(BroadcastAudience.TRIAL, "btn-broadcast.trial"),
    ),
    SwitchTo(I18nFormat("btn-back.general"), id="back", state=DashboardBroadcast.MAIN),
    IgnoreUpdate(),
    state=DashboardBroadcast.TOBEVPN_AUDIENCE,
)

tobevpn_plan = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-broadcast-plan-select"),
    Column(
        Select(
            text=I18nFormat(
                "btn-broadcast.plan-title", name=F["item"]["name"], is_active=F["item"]["is_active"]
            ),
            id="plan",
            item_id_getter=lambda item: item["id"],
            items="plans",
            type_factory=int,
            on_click=select_plan,
        ),
    ),
    SwitchTo(I18nFormat("btn-back.general"), id="back", state=DashboardBroadcast.TOBEVPN_AUDIENCE),
    IgnoreUpdate(),
    state=DashboardBroadcast.TOBEVPN_PLAN,
    getter=plans_getter,
)

tobevpn_content = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-tobevpn-broadcast-content"),
    SwitchTo(I18nFormat("btn-back.general"), id="back", state=DashboardBroadcast.TOBEVPN_AUDIENCE),
    MessageInput(enter_content, content_types=[ContentType.TEXT]),
    IgnoreUpdate(),
    state=DashboardBroadcast.TOBEVPN_CONTENT,
)

tobevpn_confirm = Window(
    I18nFormat("msg-tobevpn-broadcast-preview"),
    Button(I18nFormat("btn-tobevpn-broadcast.action"), id="plans", on_click=toggle_plans),
    Button(I18nFormat("btn-tobevpn-broadcast.publish"), id="publish", on_click=publish_tobevpn),
    SwitchTo(I18nFormat("btn-back.general"), id="back", state=DashboardBroadcast.TOBEVPN_CONTENT),
    IgnoreUpdate(),
    state=DashboardBroadcast.TOBEVPN_PREVIEW,
    getter=tobevpn_preview,
)

tobevpn_published = Window(
    I18nFormat("msg-tobevpn-broadcast-published"),
    SwitchTo(I18nFormat("btn-back.general"), id="back", state=DashboardBroadcast.MAIN),
    IgnoreUpdate(),
    state=DashboardBroadcast.TOBEVPN_PUBLISHED,
)
