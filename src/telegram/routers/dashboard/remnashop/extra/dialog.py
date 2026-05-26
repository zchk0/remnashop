from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.input import MessageInput

from src.core.enums import BannerName
from src.telegram.states import DashboardRemnashop, RemnashopExtra
from src.telegram.widgets import Banner, I18nFormat, IgnoreUpdate
from src.telegram.widgets.kbd import Button, Row, Start, SwitchTo

from .getters import extra_getter
from .handlers import (
    on_cooldown_input,
    on_enter_device_all_cd,
    on_enter_device_single_cd,
    on_enter_link_cd,
    on_enter_referral_cd,
    on_toggle_device_all,
    on_toggle_device_single,
    on_toggle_link,
    on_toggle_referral,
)

main = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-extra-main"),
    Row(
        Button(
            text=I18nFormat("btn-extra.device-single-toggle"),
            id="device_single_toggle",
            on_click=on_toggle_device_single,
        ),
        Button(
            text=I18nFormat("btn-extra.device-single-cd"),
            id="device_single_cd",
            on_click=on_enter_device_single_cd,
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-extra.device-all-toggle"),
            id="device_all_toggle",
            on_click=on_toggle_device_all,
        ),
        Button(
            text=I18nFormat("btn-extra.device-all-cd"),
            id="device_all_cd",
            on_click=on_enter_device_all_cd,
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-extra.link-toggle"),
            id="link_toggle",
            on_click=on_toggle_link,
        ),
        Button(
            text=I18nFormat("btn-extra.link-cd"),
            id="link_cd",
            on_click=on_enter_link_cd,
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-extra.referral-toggle"),
            id="referral_toggle",
            on_click=on_toggle_referral,
        ),
        Button(
            text=I18nFormat("btn-extra.referral-cd"),
            id="referral_cd",
            on_click=on_enter_referral_cd,
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardRemnashop.MAIN,
            mode=StartMode.RESET_STACK,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopExtra.MAIN,
    getter=extra_getter,
)

device_single_cd = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-extra-set-cd"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopExtra.MAIN,
        ),
    ),
    MessageInput(func=on_cooldown_input),
    IgnoreUpdate(),
    state=RemnashopExtra.DEVICE_SINGLE_CD,
    getter=extra_getter,
)

device_all_cd = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-extra-set-cd"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopExtra.MAIN,
        ),
    ),
    MessageInput(func=on_cooldown_input),
    IgnoreUpdate(),
    state=RemnashopExtra.DEVICE_ALL_CD,
    getter=extra_getter,
)

link_cd = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-extra-set-cd"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopExtra.MAIN,
        ),
    ),
    MessageInput(func=on_cooldown_input),
    IgnoreUpdate(),
    state=RemnashopExtra.LINK_CD,
    getter=extra_getter,
)

referral_cd = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-extra-set-cd"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopExtra.MAIN,
        ),
    ),
    MessageInput(func=on_cooldown_input),
    IgnoreUpdate(),
    state=RemnashopExtra.REFERRAL_CD,
    getter=extra_getter,
)

router = Dialog(
    main,
    device_single_cd,
    device_all_cd,
    link_cd,
    referral_cd,
)
