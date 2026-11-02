from html import escape
from typing import Any

from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.application.common import Notifier
from src.application.common.dao import PaymentGatewayDao
from src.application.dto.payment_gateway import FlippayGatewaySettingsDto
from src.application.use_cases.gateways.commands.flippay_methods import (
    RefreshFlippayPaymentMethods,
    UpdateFlippayPaymentMethod,
    UpdateFlippayPaymentMethodDto,
)
from src.core.constants import USER_KEY
from src.telegram.states import RemnashopGateways


@inject
async def flippay_methods_getter(
    dialog_manager: DialogManager,
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    **kwargs: Any,
) -> dict[str, Any]:
    gateway = await payment_gateway_dao.get_by_id(dialog_manager.dialog_data["gateway_id"])
    if gateway is None or not isinstance(gateway.settings, FlippayGatewaySettingsDto):
        raise ValueError("FlipPay gateway not found")
    methods = gateway.settings.payment_methods
    data: dict[str, Any] = {
        "methods_loaded": gateway.settings.methods is not None,
        "methods": [
            {
                "id": method.id,
                "title": method.title,
                "status": "⚪" if not method.available else ("🟢" if method.enabled else "🔴"),
            }
            for method in methods
        ],
    }
    selected_id = dialog_manager.dialog_data.get("flippay_method_id")
    method = next((entry for entry in methods if entry.id == selected_id), None)
    if method:
        data.update(
            method_id=method.id,
            method_code=escape(method.code),
            method_name=escape(method.name),
            method_title=method.display_name or escape(method.name),
            minimum=format(method.min_amount, ".2f"),
            enabled=method.enabled,
            available=method.available,
        )
    return data


async def on_flippay_method_select(
    callback: CallbackQuery, widget: Select, dialog_manager: DialogManager, method_id: int
) -> None:
    dialog_manager.dialog_data["flippay_method_id"] = method_id
    await dialog_manager.switch_to(RemnashopGateways.FLIPPAY_METHOD)


@inject
async def on_flippay_methods_refresh(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    refresh_methods: FromDishka[RefreshFlippayPaymentMethods],
    notifier: FromDishka[Notifier],
) -> None:
    user = dialog_manager.middleware_data[USER_KEY]
    try:
        await refresh_methods(user, dialog_manager.dialog_data["gateway_id"])
    except Exception as error:
        logger.warning("Could not refresh FlipPay payment methods: {}", type(error).__name__)
        await notifier.notify_user(user, i18n_key="ntf-flippay-methods-refresh-failed")
        return
    await notifier.notify_user(user, i18n_key="ntf-flippay-methods-refreshed")


@inject
async def on_flippay_method_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    update_method: FromDishka[UpdateFlippayPaymentMethod],
    notifier: FromDishka[Notifier],
) -> None:
    user = dialog_manager.middleware_data[USER_KEY]
    try:
        await update_method(
            user,
            UpdateFlippayPaymentMethodDto(
                dialog_manager.dialog_data["gateway_id"],
                dialog_manager.dialog_data["flippay_method_id"],
                "toggle",
            ),
        )
    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-flippay-method-unavailable")


@inject
async def on_flippay_method_name_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    update_method: FromDishka[UpdateFlippayPaymentMethod],
    notifier: FromDishka[Notifier],
) -> None:
    user = dialog_manager.middleware_data[USER_KEY]
    try:
        await update_method(
            user,
            UpdateFlippayPaymentMethodDto(
                dialog_manager.dialog_data["gateway_id"],
                dialog_manager.dialog_data["flippay_method_id"],
                "rename",
                message.html_text,
            ),
        )
    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return
    await dialog_manager.switch_to(RemnashopGateways.FLIPPAY_METHOD)


@inject
async def on_flippay_method_name_reset(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    update_method: FromDishka[UpdateFlippayPaymentMethod],
) -> None:
    await update_method(
        dialog_manager.middleware_data[USER_KEY],
        UpdateFlippayPaymentMethodDto(
            dialog_manager.dialog_data["gateway_id"],
            dialog_manager.dialog_data["flippay_method_id"],
            "reset_name",
        ),
    )
    await dialog_manager.switch_to(RemnashopGateways.FLIPPAY_METHOD)
