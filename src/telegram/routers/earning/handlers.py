from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.application.common import TranslatorRunner
from src.application.use_cases.earning.rewards import ClaimChannelReward, EarningError
from src.core.constants import USER_KEY
from src.telegram.states import Earning


async def on_task_select(
    callback: CallbackQuery,
    widget: Select[str],
    dialog_manager: DialogManager,
    item_id: str,
) -> None:
    dialog_manager.dialog_data["task_id"] = int(item_id)
    await dialog_manager.switch_to(Earning.TASK)


@inject
async def on_check(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    claim_channel_reward: FromDishka[ClaimChannelReward],
    i18n: FromDishka[TranslatorRunner],
) -> None:
    user = dialog_manager.middleware_data[USER_KEY]
    try:
        await claim_channel_reward(user, dialog_manager.dialog_data["task_id"])
    except EarningError as error:
        await callback.answer(i18n.get(str(error)), show_alert=True)
        return
    except TelegramAPIError:
        await callback.answer(i18n.get("ntf-earning.telegram-error"), show_alert=True)
        return
    except Exception:
        logger.exception(f"Channel reward failed for user {user.id}")
        await callback.answer(i18n.get("ntf-earning.retry"), show_alert=True)
        return
    await callback.answer(i18n.get("ntf-earning.success"), show_alert=True)
    await dialog_manager.switch_to(Earning.MAIN)
