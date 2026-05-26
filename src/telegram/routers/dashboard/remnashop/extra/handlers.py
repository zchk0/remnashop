from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common import Notifier
from src.application.dto import TelegramUserDto
from src.application.use_cases.settings.commands.extra import (
    ToggleResetFeature,
    ToggleResetFeatureDto,
    UpdateResetCooldown,
    UpdateResetCooldownDto,
)
from src.core.constants import USER_KEY
from src.telegram.states import RemnashopExtra

_FEATURE_DEVICE_SINGLE = "device_single_reset"
_FEATURE_DEVICE_ALL = "device_all_reset"
_FEATURE_LINK = "link_reset"
_FEATURE_REFERRAL = "referral_reset"
_CD_STATE_KEY = "cd_feature"


@inject
async def on_toggle_device_single(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    toggle_reset_feature: FromDishka[ToggleResetFeature],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await toggle_reset_feature(user, ToggleResetFeatureDto(feature=_FEATURE_DEVICE_SINGLE))


@inject
async def on_toggle_device_all(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    toggle_reset_feature: FromDishka[ToggleResetFeature],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await toggle_reset_feature(user, ToggleResetFeatureDto(feature=_FEATURE_DEVICE_ALL))


@inject
async def on_toggle_link(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    toggle_reset_feature: FromDishka[ToggleResetFeature],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await toggle_reset_feature(user, ToggleResetFeatureDto(feature=_FEATURE_LINK))


@inject
async def on_toggle_referral(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    toggle_reset_feature: FromDishka[ToggleResetFeature],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await toggle_reset_feature(user, ToggleResetFeatureDto(feature=_FEATURE_REFERRAL))


async def _enter_cd_state(dialog_manager: DialogManager, feature: str, state: object) -> None:
    dialog_manager.dialog_data[_CD_STATE_KEY] = feature
    await dialog_manager.switch_to(state)  # type: ignore[arg-type]


async def on_enter_device_single_cd(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    await _enter_cd_state(dialog_manager, _FEATURE_DEVICE_SINGLE, RemnashopExtra.DEVICE_SINGLE_CD)


async def on_enter_device_all_cd(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    await _enter_cd_state(dialog_manager, _FEATURE_DEVICE_ALL, RemnashopExtra.DEVICE_ALL_CD)


async def on_enter_link_cd(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    await _enter_cd_state(dialog_manager, _FEATURE_LINK, RemnashopExtra.LINK_CD)


async def on_enter_referral_cd(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    await _enter_cd_state(dialog_manager, _FEATURE_REFERRAL, RemnashopExtra.REFERRAL_CD)


@inject
async def on_cooldown_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notifier: FromDishka[Notifier],
    update_reset_cooldown: FromDishka[UpdateResetCooldown],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    feature = dialog_manager.dialog_data.get(_CD_STATE_KEY, "")
    raw_value = message.text

    try:
        if not raw_value:
            raise ValueError
        await update_reset_cooldown(
            user, UpdateResetCooldownDto(feature=feature, raw_value=raw_value)
        )
    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    dialog_manager.show_mode = ShowMode.DELETE_AND_SEND
    await dialog_manager.switch_to(RemnashopExtra.MAIN)
