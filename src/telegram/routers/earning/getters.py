from html import escape
from typing import Any

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common import BotService, TranslatorRunner
from src.application.common.dao import SettingsDao
from src.application.dto import SubscriptionDto, TelegramUserDto
from src.application.dto.earning import ChannelTaskDto
from src.application.use_cases.earning.rewards import GetEarningTasks


def reward_text(
    task: ChannelTaskDto,
    subscription: SubscriptionDto | None,
    i18n: TranslatorRunner,
) -> str:
    parts = []
    if task.days:
        parts.append(i18n.get("earning-reward-days", days=task.reward_days(subscription)))
    if task.reset_traffic:
        parts.append(i18n.get("earning-reward-reset"))
    if task.discount:
        parts.append(i18n.get("earning-reward-discount", discount=task.discount))
    return ", ".join(parts)


@inject
async def earning_getter(
    dialog_manager: DialogManager,
    user: TelegramUserDto,
    get_earning_tasks: FromDishka[GetEarningTasks],
    settings_dao: FromDishka[SettingsDao],
    bot_service: FromDishka[BotService],
    i18n: FromDishka[TranslatorRunner],
    **kwargs: Any,
) -> dict[str, Any]:
    settings = await settings_dao.get()
    result = await get_earning_tasks(user)
    selected = next(
        (task for task in result.tasks if task.id == dialog_manager.dialog_data.get("task_id")),
        None,
    )
    remaining = (
        "∞"
        if not selected or selected.max_claims is None
        else str(max(0, selected.max_claims - selected.claims_count))
    )
    return {
        "tasks": [
            {
                "id": task.id,
                "label": f"{task.title} — {reward_text(task, result.subscription, i18n)}",
            }
            for task in result.tasks
        ],
        "has_tasks": bool(result.tasks),
        "task_available": selected is not None,
        "title": escape(selected.title) if selected else "",
        "reward": reward_text(selected, result.subscription, i18n) if selected else "",
        "channel_url": selected.channel_url if selected else "https://t.me",
        "remaining": remaining,
        "allowed": settings.earning.allows(user),
        "price": escape(settings.earning.subscriber_price),
        "support_url": bot_service.get_support_url(i18n.get("earning-advertise-request")),
    }
