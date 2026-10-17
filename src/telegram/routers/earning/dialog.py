from aiogram_dialog import Dialog
from aiogram_dialog.widgets.text import Format
from magic_filter import F

from src.core.enums import BannerName
from src.telegram.keyboards import back_main_menu_button
from src.telegram.states import Earning
from src.telegram.widgets import Banner, I18nFormat, IgnoreUpdate
from src.telegram.widgets.kbd import Button, Row, ScrollingGroup, Select, SwitchTo, Url
from src.telegram.window import Window

from .getters import earning_getter
from .handlers import on_check, on_task_select

router = Dialog(
    Window(
        Banner(BannerName.EARNING),
        I18nFormat("msg-earning-main"),
        I18nFormat("msg-earning-empty", ~F["has_tasks"]),
        ScrollingGroup(
            Select(
                Format("{item[label]}"),
                id="task",
                on_click=on_task_select,
                item_id_getter=lambda item: item["id"],
                items="tasks",
            ),
            id="tasks_scroll",
            width=1,
            height=7,
            hide_on_single_page=True,
        ),
        Row(
            SwitchTo(
                I18nFormat("btn-earning.advertise"),
                id="advertise",
                state=Earning.ADVERTISE,
                when=F["allowed"],
            )
        ),
        *back_main_menu_button,
        IgnoreUpdate(),
        state=Earning.MAIN,
        getter=earning_getter,
    ),
    Window(
        Banner(BannerName.EARNING),
        I18nFormat("msg-earning-task", F["task_available"]),
        I18nFormat("msg-earning-empty", ~F["task_available"]),
        Row(
            Url(
                I18nFormat("btn-earning.open-channel"),
                Format("{channel_url}"),
                when=F["task_available"],
            )
        ),
        Row(
            Button(
                I18nFormat("btn-earning.check"),
                id="check",
                on_click=on_check,
                when=F["task_available"],
            )
        ),
        Row(SwitchTo(I18nFormat("btn-back.general"), id="back", state=Earning.MAIN)),
        IgnoreUpdate(),
        state=Earning.TASK,
        getter=earning_getter,
    ),
    Window(
        Banner(BannerName.EARNING),
        I18nFormat("msg-earning-advertise", F["allowed"]),
        Row(Url(I18nFormat("btn-menu.support"), Format("{support_url}"), when=F["allowed"])),
        Row(SwitchTo(I18nFormat("btn-back.general"), id="back", state=Earning.MAIN)),
        IgnoreUpdate(),
        state=Earning.ADVERTISE,
        getter=earning_getter,
    ),
)
