from adaptix import Retort
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common import Notifier
from src.application.dto import AdLinkDto
from src.application.use_cases.ad_link.commands.manage import (
    CreateAdLink,
    CreateAdLinkDto,
    DeleteAdLink,
    UpdateAdLink,
    UpdateAdLinkDto,
)
from src.application.use_cases.ad_link.queries.list import GetAdLinks
from src.core.constants import USER_KEY
from src.telegram.states import RemnashopAdvertising
from src.telegram.utils import is_double_click


@inject
async def on_link_select(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    get_ad_links: FromDishka[GetAdLinks],
    retort: FromDishka[Retort],
) -> None:
    link_id = int(dialog_manager.item_id)  # type: ignore[attr-defined]
    user = dialog_manager.middleware_data[USER_KEY]
    links = await get_ad_links(user)
    link = next((lnk for lnk in links if lnk.id == link_id), None)
    if link is None:
        return
    dialog_manager.dialog_data[AdLinkDto.__name__] = retort.dump(link)
    await dialog_manager.switch_to(RemnashopAdvertising.CONFIGURATOR)


@inject
async def on_active_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
) -> None:
    raw = dialog_manager.dialog_data.get(AdLinkDto.__name__)
    if not raw:
        return
    link = retort.load(raw, AdLinkDto)
    link.is_active = not link.is_active
    dialog_manager.dialog_data[AdLinkDto.__name__] = retort.dump(link)


@inject
async def on_name_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user = dialog_manager.middleware_data[USER_KEY]

    if not message.text or not message.text.strip():
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    raw = dialog_manager.dialog_data.get(AdLinkDto.__name__)
    link = retort.load(raw, AdLinkDto) if raw else AdLinkDto(name="", code="")
    link.name = message.text.strip()
    dialog_manager.dialog_data[AdLinkDto.__name__] = retort.dump(link)
    await dialog_manager.switch_to(RemnashopAdvertising.CONFIGURATOR)


@inject
async def on_code_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user = dialog_manager.middleware_data[USER_KEY]

    raw = dialog_manager.dialog_data.get(AdLinkDto.__name__)
    link = retort.load(raw, AdLinkDto) if raw else AdLinkDto(name="", code="")

    if not message.text:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    if message.text.strip() == "-":
        link.code = ""
    elif message.text.strip():
        link.code = message.text.strip()
    else:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    dialog_manager.dialog_data[AdLinkDto.__name__] = retort.dump(link)
    await dialog_manager.switch_to(RemnashopAdvertising.CONFIGURATOR)


@inject
async def on_link_confirm(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
    create_ad_link: FromDishka[CreateAdLink],
    update_ad_link: FromDishka[UpdateAdLink],
) -> None:
    if is_double_click(dialog_manager, key="ad_link_confirm"):
        return

    user = dialog_manager.middleware_data[USER_KEY]
    raw = dialog_manager.dialog_data.get(AdLinkDto.__name__)
    if not raw:
        return
    link = retort.load(raw, AdLinkDto)

    if not link.name:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    try:
        if link.id:
            await update_ad_link(user, UpdateAdLinkDto(link=link))
        else:
            result = await create_ad_link(
                user, CreateAdLinkDto(name=link.name, code=link.code or None)
            )
            dialog_manager.dialog_data[AdLinkDto.__name__] = retort.dump(result)
    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    await dialog_manager.switch_to(RemnashopAdvertising.MAIN)


@inject
async def on_link_delete(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    delete_ad_link: FromDishka[DeleteAdLink],
) -> None:
    if is_double_click(dialog_manager, key="ad_link_delete"):
        return

    user = dialog_manager.middleware_data[USER_KEY]
    raw = dialog_manager.dialog_data.get(AdLinkDto.__name__)
    if not raw:
        return
    link = retort.load(raw, AdLinkDto)

    await delete_ad_link(user, link.id)
    dialog_manager.dialog_data.pop(AdLinkDto.__name__, None)
    await dialog_manager.switch_to(RemnashopAdvertising.MAIN)
