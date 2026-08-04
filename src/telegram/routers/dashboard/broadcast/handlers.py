import html
import re
from typing import Any, Optional
from uuid import UUID

from adaptix import Retort
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram_dialog import DialogManager, ShowMode
from aiogram_dialog.utils import remove_intent_id
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.application.common import BotService, Notifier, TranslatorRunner
from src.application.common.dao import BroadcastDao, SettingsDao
from src.application.dto import MediaDescriptorDto, MessagePayloadDto, TelegramUserDto
from src.application.use_cases.broadcast.commands.lifecycle import (
    CancelBroadcast,
    DeleteBroadcast,
    StartBroadcast,
    StartBroadcastDto,
)
from src.application.use_cases.broadcast.queries.audience import (
    BROADCAST_REGISTRATION_EXCLUSION_DAYS,
    GetBroadcastAudienceCount,
    GetBroadcastAudienceCountDto,
    HasAvailableBroadcastPlans,
)
from src.core.constants import (
    RAW_BUTTON_TEXT_PREFIX,
    TEXT_MAX_LENGTH,
    TEXT_MEDIA_MAX_LENGTH,
    USER_KEY,
)
from src.core.enums import BroadcastAudience, MediaType
from src.core.utils.validators import is_valid_url
from src.telegram.keyboards import CLOSE_BUTTON_ID, get_broadcast_buttons
from src.telegram.states import DashboardBroadcast
from src.telegram.utils import is_double_click

MAX_EXCLUDED_TELEGRAM_IDS = 1000
MAX_TELEGRAM_ID = 9_223_372_036_854_775_807


def _update_payload(
    dialog_manager: DialogManager,
    retort: Retort,
    **updates: Any,
) -> MessagePayloadDto:
    raw_payload = dialog_manager.dialog_data.get("payload")

    old_payload = (
        retort.load(raw_payload, MessagePayloadDto)
        if raw_payload
        else MessagePayloadDto(
            i18n_key="raw-message",
            disable_default_markup=False,
            delete_after=None,
        )
    )
    payload_data: dict = retort.dump(old_payload, MessagePayloadDto)
    payload_data.update(updates)
    dialog_manager.dialog_data["payload"] = payload_data
    return retort.load(payload_data, MessagePayloadDto)


def _is_custom_button_ready(dialog_manager: DialogManager) -> bool:
    custom_button: dict[str, Any] = dialog_manager.dialog_data.get("custom_button", {})
    return bool(custom_button.get("text") and custom_button.get("url"))


def _is_custom_button_enabled(dialog_manager: DialogManager) -> bool:
    custom_button: dict[str, Any] = dialog_manager.dialog_data.get("custom_button", {})
    return bool(custom_button.get("enabled", False))


def _parse_excluded_telegram_ids(raw: str) -> list[int]:
    tokens = [token for token in re.split(r"[\s,;]+", raw.strip()) if token]
    if not tokens or any(not token.isdigit() for token in tokens):
        raise ValueError("Telegram IDs must be positive integers")

    telegram_ids = sorted({int(token) for token in tokens})
    if any(telegram_id <= 0 or telegram_id > MAX_TELEGRAM_ID for telegram_id in telegram_ids):
        raise ValueError("Telegram ID is outside the supported range")
    if len(telegram_ids) > MAX_EXCLUDED_TELEGRAM_IDS:
        raise OverflowError("Too many excluded Telegram IDs")
    return telegram_ids


async def _refresh_audience_count(
    dialog_manager: DialogManager,
    user: TelegramUserDto,
    get_broadcast_audience_count: GetBroadcastAudienceCount,
) -> int:
    audience: Optional[BroadcastAudience] = dialog_manager.dialog_data.get("audience_type")
    if audience is None:
        raise ValueError("BroadcastAudience not found in dialog data")

    count = await get_broadcast_audience_count(
        user,
        GetBroadcastAudienceCountDto(
            audience=audience,
            plan_id=dialog_manager.dialog_data.get("plan_id"),
            excluded_telegram_ids=dialog_manager.dialog_data.get(
                "excluded_telegram_ids", []
            ),
            exclude_registered_older_than_days=dialog_manager.dialog_data.get(
                "exclude_registered_older_than_days"
            ),
        ),
    )
    dialog_manager.dialog_data["audience_count"] = count
    return count


async def _sync_payload_keyboard(
    dialog_manager: DialogManager,
    bot_service: BotService,
    retort: Retort,
    i18n: TranslatorRunner,
    settings_dao: SettingsDao,
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    settings = await settings_dao.get()
    all_buttons = get_broadcast_buttons(
        support_url=bot_service.get_support_url(
            text=i18n.get("message.help", telegram_id=user.telegram_id)
        ),
        is_referral_enable=settings.referral.enable,
    )
    goto_buttons = all_buttons[:-1]
    selected_buttons: list[dict] = dialog_manager.dialog_data.get("buttons", [])

    builder = InlineKeyboardBuilder()
    has_buttons = False
    for button in selected_buttons:
        button_id = int(button["id"])
        if button.get("selected") and 0 <= button_id < len(goto_buttons):
            builder.row(goto_buttons[button_id])
            has_buttons = True

    custom_button: dict[str, Any] = dialog_manager.dialog_data.get("custom_button", {})
    custom_text = custom_button.get("text")
    custom_url = custom_button.get("url")
    if custom_button.get("enabled") and custom_text and custom_url:
        builder.row(
            InlineKeyboardButton(
                text=f"{RAW_BUTTON_TEXT_PREFIX}{custom_text}",
                url=custom_url,
            )
        )
        has_buttons = True

    reply_markup = builder.as_markup().model_dump() if has_buttons else None
    _update_payload(dialog_manager, retort, reply_markup=reply_markup)


@inject
async def on_broadcast_list(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    broadcast_dao: FromDishka[BroadcastDao],
    notifier: FromDishka[Notifier],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    broadcasts = await broadcast_dao.get_all()

    if not broadcasts:
        await notifier.notify_user(user, i18n_key="ntf-broadcast.list-empty")
        return

    await dialog_manager.switch_to(state=DashboardBroadcast.LIST)


@inject
async def on_broadcast_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_broadcast: UUID,
) -> None:
    dialog_manager.dialog_data["task_id"] = selected_broadcast
    await dialog_manager.switch_to(state=DashboardBroadcast.VIEW)


@inject
async def on_audience_select(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    get_broadcast_audience_count: FromDishka[GetBroadcastAudienceCount],
    has_available_plans: FromDishka[HasAvailableBroadcastPlans],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    if not callback.data:
        raise ValueError("Callback data is empty")

    audience = BroadcastAudience(remove_intent_id(callback.data)[-1])
    dialog_manager.dialog_data["audience_type"] = audience

    if audience == BroadcastAudience.PLAN:
        # The audience size is per-plan; here we only gate on plan availability.
        if not await has_available_plans(user):
            await notifier.notify_user(user, i18n_key="ntf-broadcast.plans-unavailable")
            return
        await dialog_manager.switch_to(state=DashboardBroadcast.PLAN)
        return

    audience_count = await get_broadcast_audience_count(
        user, GetBroadcastAudienceCountDto(audience)
    )
    if audience_count == 0:
        await notifier.notify_user(user, i18n_key="ntf-broadcast.audience-unavailable")
        return

    dialog_manager.dialog_data["audience_count"] = audience_count
    await dialog_manager.switch_to(state=DashboardBroadcast.SEND)


@inject
async def on_plan_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_plan_id: int,
    notifier: FromDishka[Notifier],
    get_broadcast_audience_count: FromDishka[GetBroadcastAudienceCount],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    audience_count = await get_broadcast_audience_count(
        user,
        GetBroadcastAudienceCountDto(audience=BroadcastAudience.PLAN, plan_id=selected_plan_id),
    )

    if audience_count == 0:
        await notifier.notify_user(user, i18n_key="ntf-broadcast.audience-unavailable")
        return

    dialog_manager.dialog_data["plan_id"] = selected_plan_id
    dialog_manager.dialog_data["audience_count"] = audience_count
    await dialog_manager.switch_to(state=DashboardBroadcast.SEND)


@inject
async def on_content_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    media_type: Optional[MediaType] = None
    file_id: Optional[str] = None

    if message.photo:
        media_type = MediaType.PHOTO
        file_id = message.photo[-1].file_id
    elif message.video:
        media_type = MediaType.VIDEO
        file_id = message.video.file_id
    elif message.animation:
        media_type = MediaType.GIF
        file_id = message.animation.file_id
    elif message.document:
        media_type = MediaType.DOCUMENT
        file_id = message.document.file_id
    elif message.sticker:
        media_type = MediaType.DOCUMENT
        file_id = message.sticker.file_id

    if not (message.html_text or file_id):
        logger.warning(f"{user.log} Provided invalid or empty content")
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    max_length = TEXT_MEDIA_MAX_LENGTH if file_id else TEXT_MAX_LENGTH
    if message.html_text and len(message.html_text) > max_length:
        logger.warning(
            f"{user.log} Message text exceeds limit: '{len(message.html_text)}' > '{max_length}'"
        )
        await notifier.notify_user(
            user,
            MessagePayloadDto(
                i18n_key="ntf-broadcast.text-too-long",
                i18n_kwargs={"max_limit": max_length},
            ),
        )
        return

    _update_payload(
        dialog_manager,
        retort,
        i18n_kwargs={"content": html.unescape(message.html_text)},
        media_type=media_type,
        media=retort.dump(MediaDescriptorDto(kind="file_id", value=file_id)) if file_id else None,
    )

    logger.info(f"{user.log} Updated message payload (content only)")
    await notifier.notify_user(user, i18n_key="ntf-broadcast.content-saved")


@inject
async def on_button_select(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    bot_service: FromDishka[BotService],
    retort: FromDishka[Retort],
    i18n: FromDishka[TranslatorRunner],
    settings_dao: FromDishka[SettingsDao],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    selected_id = int(dialog_manager.item_id)  # type: ignore[attr-defined]

    buttons: list[dict] = dialog_manager.dialog_data.get("buttons", [])
    for button in buttons:
        if button["id"] == selected_id:
            button["selected"] = not button.get("selected", False)
            break

    if selected_id == CLOSE_BUTTON_ID:
        close_selected = next((b["selected"] for b in buttons if b["id"] == CLOSE_BUTTON_ID), True)
        _update_payload(dialog_manager, retort, disable_default_markup=not close_selected)
    else:
        await _sync_payload_keyboard(
            dialog_manager,
            bot_service,
            retort,
            i18n,
            settings_dao,
        )

    logger.debug(f"{user.log} Updated payload keyboard: {buttons}")


@inject
async def on_custom_button_text_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    bot_service: FromDishka[BotService],
    retort: FromDishka[Retort],
    i18n: FromDishka[TranslatorRunner],
    settings_dao: FromDishka[SettingsDao],
    notifier: FromDishka[Notifier],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    text = (message.text or "").strip()

    if not 1 <= len(text) <= 64:
        await notifier.notify_user(user, i18n_key="ntf-broadcast.custom-button-text-invalid")
        return

    custom_button = dict(dialog_manager.dialog_data.get("custom_button", {}))
    custom_button["text"] = text
    dialog_manager.dialog_data["custom_button"] = custom_button
    await _sync_payload_keyboard(dialog_manager, bot_service, retort, i18n, settings_dao)

    logger.info(f"{user.log} Updated custom broadcast button text")
    await notifier.notify_user(user, i18n_key="ntf-broadcast.custom-button-saved")
    await dialog_manager.switch_to(DashboardBroadcast.CUSTOM_BUTTON)


@inject
async def on_custom_button_url_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    bot_service: FromDishka[BotService],
    retort: FromDishka[Retort],
    i18n: FromDishka[TranslatorRunner],
    settings_dao: FromDishka[SettingsDao],
    notifier: FromDishka[Notifier],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    url = (message.text or "").strip()

    if len(url) > 2048 or not is_valid_url(url):
        await notifier.notify_user(user, i18n_key="ntf-broadcast.custom-button-url-invalid")
        return

    custom_button = dict(dialog_manager.dialog_data.get("custom_button", {}))
    custom_button["url"] = url
    dialog_manager.dialog_data["custom_button"] = custom_button
    await _sync_payload_keyboard(dialog_manager, bot_service, retort, i18n, settings_dao)

    logger.info(f"{user.log} Updated custom broadcast button URL")
    await notifier.notify_user(user, i18n_key="ntf-broadcast.custom-button-saved")
    await dialog_manager.switch_to(DashboardBroadcast.CUSTOM_BUTTON)


@inject
async def on_custom_button_delete(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    bot_service: FromDishka[BotService],
    retort: FromDishka[Retort],
    i18n: FromDishka[TranslatorRunner],
    settings_dao: FromDishka[SettingsDao],
    notifier: FromDishka[Notifier],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    dialog_manager.dialog_data.pop("custom_button", None)
    await _sync_payload_keyboard(dialog_manager, bot_service, retort, i18n, settings_dao)

    logger.info(f"{user.log} Deleted custom broadcast button")
    await notifier.notify_user(user, i18n_key="ntf-broadcast.custom-button-deleted")


@inject
async def on_custom_button_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    bot_service: FromDishka[BotService],
    retort: FromDishka[Retort],
    i18n: FromDishka[TranslatorRunner],
    settings_dao: FromDishka[SettingsDao],
    notifier: FromDishka[Notifier],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    custom_button = dict(dialog_manager.dialog_data.get("custom_button", {}))

    if not custom_button.get("enabled") and not _is_custom_button_ready(dialog_manager):
        await notifier.notify_user(user, i18n_key="ntf-broadcast.custom-button-incomplete")
        await dialog_manager.switch_to(DashboardBroadcast.CUSTOM_BUTTON)
        return

    custom_button["enabled"] = not bool(custom_button.get("enabled", False))
    dialog_manager.dialog_data["custom_button"] = custom_button
    await _sync_payload_keyboard(dialog_manager, bot_service, retort, i18n, settings_dao)

    logger.info(f"{user.log} Set custom broadcast button enabled={custom_button['enabled']}")


@inject
async def on_excluded_users_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    get_broadcast_audience_count: FromDishka[GetBroadcastAudienceCount],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    try:
        excluded_telegram_ids = _parse_excluded_telegram_ids(message.text or "")
    except OverflowError:
        await notifier.notify_user(user, i18n_key="ntf-broadcast.excluded-users-too-many")
        return
    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-broadcast.excluded-users-invalid")
        return

    dialog_manager.dialog_data["excluded_telegram_ids"] = excluded_telegram_ids
    audience_count = await _refresh_audience_count(
        dialog_manager,
        user,
        get_broadcast_audience_count,
    )
    await notifier.notify_user(
        user,
        MessagePayloadDto(
            i18n_key="ntf-broadcast.excluded-users-saved",
            i18n_kwargs={
                "excluded_count": len(excluded_telegram_ids),
                "audience_count": audience_count,
            },
        ),
    )
    logger.info(
        f"{user.log} Set '{len(excluded_telegram_ids)}' excluded Telegram IDs "
        f"for broadcast"
    )
    await dialog_manager.switch_to(DashboardBroadcast.SEND)


@inject
async def on_excluded_users_reset(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    get_broadcast_audience_count: FromDishka[GetBroadcastAudienceCount],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    dialog_manager.dialog_data["excluded_telegram_ids"] = []
    dialog_manager.dialog_data["exclude_registered_older_than_days"] = None
    await _refresh_audience_count(dialog_manager, user, get_broadcast_audience_count)
    await notifier.notify_user(user, i18n_key="ntf-broadcast.excluded-users-cleared")
    logger.info(f"{user.log} Cleared broadcast exclusions")


@inject
async def on_registration_exclusion_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_days: int,
    get_broadcast_audience_count: FromDishka[GetBroadcastAudienceCount],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    exclude_registered_older_than_days = selected_days or None
    if (
        exclude_registered_older_than_days is not None
        and exclude_registered_older_than_days not in BROADCAST_REGISTRATION_EXCLUSION_DAYS
    ):
        raise ValueError(
            f"Unsupported registration exclusion period: '{exclude_registered_older_than_days}'"
        )

    dialog_manager.dialog_data[
        "exclude_registered_older_than_days"
    ] = exclude_registered_older_than_days
    await _refresh_audience_count(dialog_manager, user, get_broadcast_audience_count)
    logger.info(
        f"{user.log} Set broadcast registration exclusion to "
        f"accounts older than '{exclude_registered_older_than_days}' days"
    )


@inject
async def on_preview(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    payload = dialog_manager.dialog_data.get("payload")

    if not payload or not payload["i18n_kwargs"].get("content") and not payload.get("media"):
        await notifier.notify_user(user, i18n_key="ntf-broadcast.content-empty")
        return

    if _is_custom_button_enabled(dialog_manager) and not _is_custom_button_ready(dialog_manager):
        await notifier.notify_user(user, i18n_key="ntf-broadcast.custom-button-incomplete")
        return

    await notifier.notify_user(user, payload=retort.load(payload, MessagePayloadDto))


@inject
async def on_view_preview(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    broadcast_dao: FromDishka[BroadcastDao],
    notifier: FromDishka[Notifier],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    task_id = dialog_manager.dialog_data.get("task_id")
    broadcast = await broadcast_dao.get_by_task_id(task_id) if task_id else None

    if not broadcast or not broadcast.payload:
        await notifier.notify_user(user, i18n_key="ntf-broadcast.content-empty")
        return

    await notifier.notify_user(user, payload=broadcast.payload)


@inject
async def on_send(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
    start_broadcast: FromDishka[StartBroadcast],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    audience: Optional[BroadcastAudience] = dialog_manager.dialog_data.get("audience_type")
    plan_id = dialog_manager.dialog_data.get("plan_id")
    payload = dialog_manager.dialog_data.get("payload")
    excluded_telegram_ids: list[int] = dialog_manager.dialog_data.get(
        "excluded_telegram_ids", []
    )
    exclude_registered_older_than_days: Optional[int] = dialog_manager.dialog_data.get(
        "exclude_registered_older_than_days"
    )

    if not payload or (
        not payload.get("i18n_kwargs", {}).get("content") and not payload.get("media")
    ):
        await notifier.notify_user(user, i18n_key="ntf-broadcast.content-empty")
        return

    if _is_custom_button_enabled(dialog_manager) and not _is_custom_button_ready(dialog_manager):
        await notifier.notify_user(user, i18n_key="ntf-broadcast.custom-button-incomplete")
        return

    if dialog_manager.dialog_data.get("audience_count", 0) <= 0:
        await notifier.notify_user(user, i18n_key="ntf-broadcast.audience-unavailable")
        return

    payload = retort.load(payload, MessagePayloadDto)

    if not audience:
        raise ValueError("BroadcastAudience not found in dialog data")

    if is_double_click(dialog_manager, key="broadcast_confirm", cooldown=5):
        task_id = await start_broadcast(
            user,
            StartBroadcastDto(
                audience,
                payload,
                plan_id,
                excluded_telegram_ids,
                exclude_registered_older_than_days,
            ),
        )
        dialog_manager.dialog_data["task_id"] = task_id
        await dialog_manager.switch_to(state=DashboardBroadcast.VIEW)
        return

    await notifier.notify_user(user, i18n_key="ntf-common.double-click-confirm")
    logger.debug(f"{user.log} Awaiting confirmation for broadcast send")


@inject
async def on_cancel(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    cancel_broadcast: FromDishka[CancelBroadcast],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    task_id = dialog_manager.dialog_data["task_id"]

    try:
        await cancel_broadcast(user, task_id)
        await notifier.notify_user(user, i18n_key="ntf-broadcast.canceled")
    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-broadcast.not-cancelable")


@inject
async def on_delete(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    delete_broadcast: FromDishka[DeleteBroadcast],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    task_id = dialog_manager.dialog_data["task_id"]

    try:
        # Deletion runs in the background; respond immediately. The task reports the
        # result summary to admins on completion (see delete_broadcast_task).
        await delete_broadcast(user, task_id)
        await notifier.notify_user(user, i18n_key="ntf-broadcast.deleting")
    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-broadcast.already-deleted")
