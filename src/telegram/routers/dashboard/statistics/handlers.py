from typing import Optional

from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.common import ManagedScroll
from aiogram_dialog.widgets.kbd import Select


async def on_gateway_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_page: int,
) -> None:
    widget_scroll: Optional[ManagedScroll] = dialog_manager.find("scroll_transactions")

    if not widget_scroll:
        raise ValueError("scroll_transactions widget not found")

    await widget_scroll.set_page(selected_page)


async def on_plan_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_page: int,
) -> None:
    widget_scroll: Optional[ManagedScroll] = dialog_manager.find("scroll_subscriptions")

    if not widget_scroll:
        raise ValueError("scroll_subscriptions widget not found")

    await widget_scroll.set_page(selected_page)
