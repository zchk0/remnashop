import html
from typing import Any

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common import BotService, TranslatorRunner
from src.application.common.dao import BroadcastDao, PlanDao, SettingsDao
from src.application.dto import PlanDto
from src.core.constants import DATETIME_VIEW_FORMAT, USER_KEY
from src.telegram.keyboards import CLOSE_BUTTON_ID, get_broadcast_buttons


@inject
async def plans_getter(
    dialog_manager: DialogManager,
    plan_dao: FromDishka[PlanDao],
    i18n: FromDishka[TranslatorRunner],
    **kwargs: Any,
) -> dict[str, Any]:
    plans: list[PlanDto] = await plan_dao.get_all()
    formatted_plans = [
        {
            "id": plan.id,
            "name": i18n.get(plan.name),
            "is_active": plan.is_active,
        }
        for plan in plans
        if not plan.is_trial
    ]

    return {
        "plans": formatted_plans,
    }


async def send_getter(
    dialog_manager: DialogManager,
    **kwargs: Any,
) -> dict[str, Any]:
    audience = dialog_manager.dialog_data["audience_type"]
    audience_count: int = dialog_manager.dialog_data["audience_count"]
    excluded_telegram_ids: list[int] = dialog_manager.dialog_data.get(
        "excluded_telegram_ids", []
    )
    exclude_registered_within_days = dialog_manager.dialog_data.get(
        "exclude_registered_within_days"
    )

    return {
        "audience_type": audience,
        "audience_count": audience_count,
        "excluded_users_count": len(excluded_telegram_ids),
        "registration_exclusion_days": exclude_registered_within_days or 0,
    }


async def excluded_users_getter(
    dialog_manager: DialogManager,
    **kwargs: Any,
) -> dict[str, Any]:
    excluded_telegram_ids: list[int] = dialog_manager.dialog_data.get(
        "excluded_telegram_ids", []
    )
    visible_ids = excluded_telegram_ids[:20]
    ids_text = ", ".join(str(telegram_id) for telegram_id in visible_ids) or "—"
    if len(excluded_telegram_ids) > len(visible_ids):
        ids_text += f" … (+{len(excluded_telegram_ids) - len(visible_ids)})"
    exclude_registered_within_days = dialog_manager.dialog_data.get(
        "exclude_registered_within_days"
    )

    return {
        "excluded_users_count": len(excluded_telegram_ids),
        "excluded_user_ids": ids_text,
        "audience_count": dialog_manager.dialog_data["audience_count"],
        "registration_exclusion_days": exclude_registered_within_days or 0,
        "registration_exclusion_periods": [
            {
                "days": days,
                "selected": (days or None) == exclude_registered_within_days,
            }
            for days in (0, 7, 30, 90)
        ],
        "has_excluded_users": bool(
            excluded_telegram_ids or exclude_registered_within_days
        ),
    }


@inject
async def buttons_getter(
    dialog_manager: DialogManager,
    bot_service: FromDishka[BotService],
    settings_dao: FromDishka[SettingsDao],
    i18n: FromDishka[TranslatorRunner],
    **kwargs: Any,
) -> dict[str, Any]:
    buttons = dialog_manager.dialog_data.get("buttons", [])
    user = dialog_manager.middleware_data[USER_KEY]
    settings = await settings_dao.get()

    if not buttons:
        all_buttons = get_broadcast_buttons(
            support_url=bot_service.get_support_url(
                text=i18n.get("message.help", telegram_id=user.telegram_id)
            ),
            is_referral_enable=settings.referral.enable,
        )
        buttons = [
            {
                "id": CLOSE_BUTTON_ID if index == len(all_buttons) - 1 else index,
                "text": btn.text,
                "selected": index == len(all_buttons) - 1,
            }
            for index, btn in enumerate(all_buttons)
        ]
        dialog_manager.dialog_data["buttons"] = buttons

    custom_button: dict[str, Any] = dialog_manager.dialog_data.get("custom_button", {})
    custom_text = custom_button.get("text")

    return {
        "buttons": buttons,
        "custom_button_label": (
            f"🔗 {custom_text}" if custom_text else i18n.get("btn-broadcast.custom-button")
        ),
        "custom_button_enabled": bool(custom_button.get("enabled", False)),
    }


async def custom_button_getter(
    dialog_manager: DialogManager,
    **kwargs: Any,
) -> dict[str, Any]:
    custom_button: dict[str, Any] = dialog_manager.dialog_data.get("custom_button", {})
    text = custom_button.get("text", "")
    url = custom_button.get("url", "")

    return {
        "custom_button_text": html.escape(text) if text else "—",
        "custom_button_url": html.escape(url) if url else "—",
        "has_custom_button": bool(custom_button),
        "custom_button_ready": bool(text and url),
        "custom_button_enabled": bool(custom_button.get("enabled", False)),
    }


@inject
async def list_getter(
    dialog_manager: DialogManager,
    broadcast_dao: FromDishka[BroadcastDao],
    **kwargs: Any,
) -> dict[str, Any]:
    broadcasts = await broadcast_dao.get_all()

    formatted_broadcasts = [
        {
            "task_id": broadcast.task_id,
            "status": broadcast.status,
            "created_at": broadcast.created_at.strftime(DATETIME_VIEW_FORMAT),  # type: ignore[union-attr]
        }
        for broadcast in broadcasts
    ]

    return {"broadcasts": formatted_broadcasts}


@inject
async def view_getter(
    dialog_manager: DialogManager,
    broadcast_dao: FromDishka[BroadcastDao],
    **kwargs: Any,
) -> dict[str, Any]:
    task_id = dialog_manager.dialog_data.get("task_id")

    if not task_id:
        raise ValueError("Task ID not found in dialog data")

    broadcast = await broadcast_dao.get_by_task_id(task_id)

    if not broadcast:
        raise ValueError(f"Broadcast '{task_id}' not found")

    return {
        "broadcast_id": str(broadcast.task_id),
        "broadcast_status": broadcast.status,
        "audience_type": broadcast.audience,
        "created_at": broadcast.created_at.strftime(DATETIME_VIEW_FORMAT),  # type: ignore[union-attr]
        "total_count": broadcast.total_count,
        "success_count": broadcast.success_count,
        "failed_count": broadcast.failed_count,
    }
