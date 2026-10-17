from dataclasses import asdict
from typing import Any
from urllib.parse import urlparse

from aiogram import Bot
from aiogram.enums import ButtonStyle, ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common import Notifier, TranslatorRunner
from src.application.common.dao import SettingsDao
from src.application.common.dao.earning import EarningDao
from src.application.common.policy import Permission, PermissionPolicy
from src.application.dto import TelegramUserDto
from src.application.dto.earning import ChannelTaskDto
from src.application.use_cases.earning.manage import ManageChannelTask, UpdateEarningSettings
from src.application.use_cases.earning.rewards import (
    EarningError,
    ResolveEarningClaim,
    ResolveEarningClaimDto,
)
from src.core.constants import USER_KEY
from src.core.exceptions import PermissionDeniedError
from src.telegram.states import DashboardEarning


def admin_actor(dialog_manager: DialogManager) -> TelegramUserDto:
    actor: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    if not PermissionPolicy.has_permission(actor, Permission.MANAGE_EARNING):
        raise PermissionDeniedError
    return actor


async def on_create(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    admin_actor(dialog_manager)
    dialog_manager.dialog_data["task"] = asdict(ChannelTaskDto())
    await dialog_manager.switch_to(DashboardEarning.TASK)


@inject
async def on_select(
    callback: CallbackQuery,
    widget: Any,
    dialog_manager: DialogManager,
    item_id: str,
    earning_dao: FromDishka[EarningDao],
) -> None:
    admin_actor(dialog_manager)
    task = await earning_dao.get_task(int(item_id))
    if task and not task.deleted:
        dialog_manager.dialog_data["task"] = asdict(task)
        await dialog_manager.switch_to(DashboardEarning.TASK)


async def on_edit(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    admin_actor(dialog_manager)
    scope, field = (widget.widget_id or "").split("_", 1)
    dialog_manager.dialog_data["input_scope"] = scope
    dialog_manager.dialog_data["input_field"] = field
    await dialog_manager.switch_to(
        DashboardEarning.PLAN if field in {"plan_id", "trial_plan_id"} else DashboardEarning.INPUT
    )


async def on_task_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    admin_actor(dialog_manager)
    field = (widget.widget_id or "").removeprefix("toggle_")
    if field in {"active", "reset_traffic"}:
        raw = dialog_manager.dialog_data["task"]
        raw[field] = not raw[field]


@inject
async def on_settings_action(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    update_settings: FromDishka[UpdateEarningSettings],
    earning_settings_dao: FromDishka[SettingsDao],
) -> None:
    actor = admin_actor(dialog_manager)
    settings = await earning_settings_dao.get()
    changes: dict[str, Any]
    widget_id = widget.widget_id or ""
    if widget_id == "enabled":
        changes = {"enabled": not settings.earning.enabled}
    elif widget_id.startswith("audience_"):
        changes = {"audience": widget_id.removeprefix("audience_")}
    else:
        value = widget_id.removeprefix("color_")
        changes = {"button_color": None if value == "default" else ButtonStyle(value)}
    await update_settings(actor, changes)
    await dialog_manager.switch_to(DashboardEarning.MAIN)


@inject
async def on_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    update_settings: FromDishka[UpdateEarningSettings],
    notifier: FromDishka[Notifier],
    bot: FromDishka[Bot],
) -> None:
    actor = admin_actor(dialog_manager)
    dialog_manager.show_mode = ShowMode.EDIT
    field = dialog_manager.dialog_data["input_field"]
    scope = dialog_manager.dialog_data["input_scope"]
    value = (message.text or "").strip()
    try:
        if not value:
            raise ValueError("Empty value")
        if scope == "setting":
            parsed: str | list[int] = value
            if field == "allowed_telegram_ids":
                parsed = (
                    []
                    if value == "0"
                    else sorted({int(item) for item in value.replace(",", " ").split()})
                )
            await update_settings(actor, {field: parsed})
        else:
            task = dialog_manager.dialog_data["task"]
            await update_task_input(task, field, value, bot)
    except (ValueError, TelegramAPIError):
        await notifier.notify_user(
            actor,
            i18n_key=(
                "ntf-earning.channel-admin-required"
                if field == "channel"
                else "ntf-common.invalid-value"
            ),
        )
        return
    await dialog_manager.switch_to(
        DashboardEarning.MAIN if scope == "setting" else DashboardEarning.TASK
    )


async def update_task_input(task: dict[str, Any], field: str, value: str, bot: Bot) -> None:
    if field == "channel":
        task.update(await channel_input(value, bot))
    elif field == "title":
        if len(value) > 128:
            raise ValueError("Title too long")
        task[field] = value
    else:
        number = int(value)
        if number < 0 or number > 2147483647 or (field == "discount" and number > 100):
            raise ValueError("Invalid number")
        if field in {"days", "trial_days"} and number > 3650:
            raise ValueError("Too many days")
        task[field] = None if field in {"max_claims", "trial_days"} and number == 0 else number


async def channel_input(value: str, bot: Bot) -> dict[str, Any]:
    parts = value.split()
    reference = parts[0]
    if reference.startswith("https://t.me/"):
        reference = "@" + urlparse(reference).path.strip("/")
    chat = await bot.get_chat(int(reference) if reference.startswith("-") else reference)
    member = await bot.get_chat_member(chat.id, bot.id)
    if chat.type != ChatType.CHANNEL or member.status not in (
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.CREATOR,
    ):
        raise ValueError("Bot must be a channel administrator")
    channel_url = (
        f"https://t.me/{chat.username}" if chat.username else (parts[1] if len(parts) == 2 else "")
    )
    url = urlparse(channel_url)
    if url.scheme != "https" or url.hostname != "t.me" or not url.path.strip("/"):
        raise ValueError("Provide a channel invite link")
    return {"channel_id": chat.id, "channel_url": channel_url, "title": chat.title or "Канал"}


async def on_input_back(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    await dialog_manager.switch_to(
        DashboardEarning.MAIN
        if dialog_manager.dialog_data.get("input_scope") == "setting"
        else DashboardEarning.TASK
    )


async def on_plan_select(
    callback: CallbackQuery,
    widget: Select[str],
    dialog_manager: DialogManager,
    item_id: str,
) -> None:
    admin_actor(dialog_manager)
    plan_id = int(item_id)
    field = dialog_manager.dialog_data["input_field"]
    dialog_manager.dialog_data["task"][field] = plan_id or None
    await dialog_manager.switch_to(DashboardEarning.TASK)


@inject
async def on_save(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    manage_task: FromDishka[ManageChannelTask],
    i18n: FromDishka[TranslatorRunner],
) -> None:
    actor = admin_actor(dialog_manager)
    task = ChannelTaskDto(**dialog_manager.dialog_data["task"])
    if widget.widget_id == "delete_confirm":
        task.deleted = True
        task.active = False
    try:
        task = await manage_task(actor, task)
    except ValueError:
        await callback.answer(i18n.get("ntf-earning.invalid-task"), show_alert=True)
        return
    dialog_manager.dialog_data["task"] = asdict(task)
    await callback.answer(i18n.get("ntf-earning.saved"))
    await dialog_manager.switch_to(DashboardEarning.MAIN)


async def on_claim_select(
    callback: CallbackQuery,
    widget: Select[str],
    dialog_manager: DialogManager,
    item_id: str,
) -> None:
    admin_actor(dialog_manager)
    task_id, user_id = item_id.split(".")
    dialog_manager.dialog_data.update(claim_task_id=int(task_id), claim_user_id=int(user_id))
    await dialog_manager.switch_to(DashboardEarning.CLAIM)


@inject
async def on_claim_resolve(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    resolve_claim: FromDishka[ResolveEarningClaim],
    i18n: FromDishka[TranslatorRunner],
) -> None:
    actor = admin_actor(dialog_manager)
    try:
        await resolve_claim(
            actor,
            ResolveEarningClaimDto(
                task_id=dialog_manager.dialog_data["claim_task_id"],
                user_id=dialog_manager.dialog_data["claim_user_id"],
                confirm_reset=widget.widget_id == "confirm_reset",
            ),
        )
    except EarningError as error:
        await callback.answer(i18n.get(str(error)), show_alert=True)
        return
    await callback.answer(i18n.get("ntf-earning.success"), show_alert=True)
    await dialog_manager.switch_to(DashboardEarning.CLAIMS)
