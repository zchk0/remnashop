from html import escape
from typing import Any

from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common import Notifier
from src.application.common.dao import PaymentGatewayDao
from src.application.dto.payment_gateway import RivaraGatewaySettingsDto
from src.application.use_cases.gateways.commands.rivara_methods import (
    UpdateRivaraPaymentMethod,
    UpdateRivaraPaymentMethodDto,
)
from src.core.constants import USER_KEY
from src.telegram.states import RemnashopGateways


@inject
async def rivara_methods_getter(
    dialog_manager: DialogManager,
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    **kwargs: Any,
) -> dict[str, Any]:
    gateway = await payment_gateway_dao.get_by_id(dialog_manager.dialog_data["gateway_id"])
    if gateway is None or not isinstance(gateway.settings, RivaraGatewaySettingsDto):
        raise ValueError("Rivara Pay gateway not found")
    methods = gateway.settings.payment_methods
    data: dict[str, Any] = {
        "methods": [
            {"id": method.id, "title": method.title, "status": "🟢" if method.enabled else "🔴"}
            for method in methods
        ],
    }
    selected_id = dialog_manager.dialog_data.get("rivara_method_id")
    method = next((entry for entry in methods if entry.id == selected_id), None)
    if method:
        data.update(
            method_id=method.id,
            method_name=escape(method.name),
            method_title=method.display_name or escape(method.name),
            enabled=method.enabled,
            is_general=method.id == "ALL",
        )
    return data


async def on_rivara_method_select(
    callback: CallbackQuery, widget: Select, dialog_manager: DialogManager, method_id: str
) -> None:
    dialog_manager.dialog_data["rivara_method_id"] = method_id
    await dialog_manager.switch_to(RemnashopGateways.RIVARA_METHOD)


@inject
async def on_rivara_method_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    update_method: FromDishka[UpdateRivaraPaymentMethod],
) -> None:
    await update_method(
        dialog_manager.middleware_data[USER_KEY],
        UpdateRivaraPaymentMethodDto(
            dialog_manager.dialog_data["gateway_id"],
            dialog_manager.dialog_data["rivara_method_id"],
            "toggle",
        ),
    )


@inject
async def on_rivara_method_name_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    update_method: FromDishka[UpdateRivaraPaymentMethod],
    notifier: FromDishka[Notifier],
) -> None:
    user = dialog_manager.middleware_data[USER_KEY]
    try:
        await update_method(
            user,
            UpdateRivaraPaymentMethodDto(
                dialog_manager.dialog_data["gateway_id"],
                dialog_manager.dialog_data["rivara_method_id"],
                "rename",
                message.html_text,
            ),
        )
    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return
    await dialog_manager.switch_to(RemnashopGateways.RIVARA_METHOD)


@inject
async def on_rivara_method_name_reset(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    update_method: FromDishka[UpdateRivaraPaymentMethod],
) -> None:
    await update_method(
        dialog_manager.middleware_data[USER_KEY],
        UpdateRivaraPaymentMethodDto(
            dialog_manager.dialog_data["gateway_id"],
            dialog_manager.dialog_data["rivara_method_id"],
            "reset_name",
        ),
    )
    await dialog_manager.switch_to(RemnashopGateways.RIVARA_METHOD)
