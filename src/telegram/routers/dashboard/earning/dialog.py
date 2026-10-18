from aiogram.enums import ButtonStyle
from aiogram_dialog import Dialog, StartMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.link_preview import LinkPreview
from aiogram_dialog.widgets.style import Style
from aiogram_dialog.widgets.text import Format
from magic_filter import F

from src.telegram.states import Dashboard, DashboardEarning
from src.telegram.widgets import I18nFormat, IgnoreUpdate
from src.telegram.widgets.kbd import Button, Row, ScrollingGroup, Select, Start, SwitchTo
from src.telegram.window import Window

from .getters import admin_getter, channels_getter
from .handlers import (
    on_claim_resolve,
    on_claim_select,
    on_create,
    on_edit,
    on_input,
    on_input_back,
    on_plan_select,
    on_reset_completions,
    on_save,
    on_select,
    on_settings_action,
    on_task_toggle,
)


def edit_button(field: str, *, setting: bool = False) -> Button:
    return Button(
        I18nFormat("btn-earning-edit-" + field.replace("_", "-")),
        id=("setting_" if setting else "task_") + field,
        on_click=on_edit,
    )


router = Dialog(
    Window(
        I18nFormat("msg-earning-admin"),
        LinkPreview(is_disabled=True),
        Row(Button(I18nFormat("btn-earning.enabled"), id="enabled", on_click=on_settings_action)),
        Row(
            SwitchTo(
                I18nFormat("btn-earning.audience"), id="audience", state=DashboardEarning.AUDIENCE
            ),
            edit_button("allowed_telegram_ids", setting=True),
        ),
        Row(
            edit_button("button_text", setting=True),
            SwitchTo(I18nFormat("btn-menu-editor.color"), id="color", state=DashboardEarning.COLOR),
        ),
        Row(edit_button("subscriber_price", setting=True)),
        Row(
            SwitchTo(I18nFormat("btn-earning.pending"), id="claims", state=DashboardEarning.CLAIMS)
        ),
        Row(
            SwitchTo(
                I18nFormat("btn-earning.channels"), id="channels", state=DashboardEarning.CHANNELS
            )
        ),
        Row(
            Start(
                I18nFormat("btn-back.general"),
                id="back",
                state=Dashboard.MAIN,
                mode=StartMode.RESET_STACK,
            )
        ),
        IgnoreUpdate(),
        state=DashboardEarning.MAIN,
        getter=admin_getter,
    ),
    Window(
        I18nFormat("msg-earning-channels"),
        LinkPreview(is_disabled=True),
        Row(Button(I18nFormat("btn-earning.create"), id="create", on_click=on_create)),
        ScrollingGroup(
            Select(
                Format("{item[label]}"),
                id="task",
                item_id_getter=lambda item: item["id"],
                items="tasks",
                on_click=on_select,
            ),
            id="task_scroll",
            width=1,
            height=6,
            hide_on_single_page=True,
        ),
        Row(SwitchTo(I18nFormat("btn-back.general"), id="back", state=DashboardEarning.MAIN)),
        IgnoreUpdate(),
        state=DashboardEarning.CHANNELS,
        getter=channels_getter,
    ),
    Window(
        I18nFormat("msg-earning-admin-task"),
        Row(Button(I18nFormat("btn-earning.active"), id="toggle_active", on_click=on_task_toggle)),
        Row(edit_button("channel"), edit_button("title")),
        Row(edit_button("days"), edit_button("discount")),
        Row(
            Button(
                I18nFormat("btn-earning.reset"), id="toggle_reset_traffic", on_click=on_task_toggle
            )
        ),
        Row(edit_button("max_claims")),
        Row(edit_button("plan_id")),
        Row(edit_button("trial_plan_id"), edit_button("trial_days")),
        Row(
            SwitchTo(
                I18nFormat("btn-earning.reset-completions"),
                id="reset_completions",
                state=DashboardEarning.RESET_CLAIMS,
                when=F["saved_task"],
            )
        ),
        Row(
            SwitchTo(
                I18nFormat("btn-earning.delete"),
                id="delete",
                state=DashboardEarning.DELETE,
                when=F["saved_task"],
                style=Style(ButtonStyle.DANGER),
            ),
            Button(
                I18nFormat("btn-earning.save"),
                id="save",
                on_click=on_save,
                style=Style(ButtonStyle.SUCCESS),
            ),
        ),
        Row(SwitchTo(I18nFormat("btn-common.cancel"), id="back", state=DashboardEarning.CHANNELS)),
        IgnoreUpdate(),
        state=DashboardEarning.TASK,
        getter=admin_getter,
    ),
    Window(
        I18nFormat("{input_key}"),
        MessageInput(on_input),
        Row(Button(I18nFormat("btn-back.general"), id="back", on_click=on_input_back)),
        IgnoreUpdate(),
        state=DashboardEarning.INPUT,
        getter=admin_getter,
    ),
    Window(
        I18nFormat("msg-earning-audience"),
        *[
            Row(
                Button(
                    I18nFormat(f"earning-audience-{audience}"),
                    id=f"audience_{audience}",
                    on_click=on_settings_action,
                )
            )
            for audience in ("all", "admins", "selected")
        ],
        Row(SwitchTo(I18nFormat("btn-back.general"), id="back", state=DashboardEarning.MAIN)),
        IgnoreUpdate(),
        state=DashboardEarning.AUDIENCE,
        getter=admin_getter,
    ),
    Window(
        I18nFormat("msg-menu-editor-button-color"),
        *[
            Row(
                Button(
                    I18nFormat(f"btn-menu-editor.color-{color.value if color else 'default'}"),
                    id=f"color_{color.value if color else 'default'}",
                    on_click=on_settings_action,
                    style=Style(color),
                )
            )
            for color in (None, *ButtonStyle)
        ],
        Row(SwitchTo(I18nFormat("btn-back.general"), id="back", state=DashboardEarning.MAIN)),
        IgnoreUpdate(),
        state=DashboardEarning.COLOR,
        getter=admin_getter,
    ),
    Window(
        I18nFormat("msg-earning-plans"),
        ScrollingGroup(
            Select(
                Format("{item[name]}"),
                id="plan",
                item_id_getter=lambda item: item["id"],
                items="plans",
                on_click=on_plan_select,
            ),
            id="plan_scroll",
            width=1,
            height=7,
            hide_on_single_page=True,
        ),
        Row(SwitchTo(I18nFormat("btn-back.general"), id="back", state=DashboardEarning.TASK)),
        IgnoreUpdate(),
        state=DashboardEarning.PLAN,
        getter=admin_getter,
    ),
    Window(
        I18nFormat("msg-earning-delete"),
        Row(
            Button(
                I18nFormat("btn-earning.delete"),
                id="delete_confirm",
                on_click=on_save,
                style=Style(ButtonStyle.DANGER),
            )
        ),
        Row(SwitchTo(I18nFormat("btn-common.cancel"), id="cancel", state=DashboardEarning.TASK)),
        IgnoreUpdate(),
        state=DashboardEarning.DELETE,
        getter=admin_getter,
    ),
    Window(
        I18nFormat("msg-earning-reset-completions"),
        Row(
            Button(
                I18nFormat("btn-earning.reset-completions"),
                id="confirm_reset_completions",
                on_click=on_reset_completions,
                style=Style(ButtonStyle.DANGER),
            )
        ),
        Row(SwitchTo(I18nFormat("btn-common.cancel"), id="back", state=DashboardEarning.TASK)),
        IgnoreUpdate(),
        state=DashboardEarning.RESET_CLAIMS,
        getter=admin_getter,
    ),
    Window(
        I18nFormat("msg-earning-pending"),
        ScrollingGroup(
            Select(
                Format("{item[label]}"),
                id="claim",
                item_id_getter=lambda item: item["id"],
                items="pending_claims",
                on_click=on_claim_select,
            ),
            id="claim_scroll",
            width=1,
            height=7,
            hide_on_single_page=True,
        ),
        Row(SwitchTo(I18nFormat("btn-back.general"), id="back", state=DashboardEarning.MAIN)),
        IgnoreUpdate(),
        state=DashboardEarning.CLAIMS,
        getter=admin_getter,
    ),
    Window(
        I18nFormat("msg-earning-claim"),
        Row(
            Button(
                I18nFormat("btn-earning.retry"),
                id="retry_claim",
                on_click=on_claim_resolve,
                when=F["claim_found"] & ~F["reset_uncertain"],
            )
        ),
        Row(
            Button(
                I18nFormat("btn-earning.confirm-reset"),
                id="confirm_reset",
                on_click=on_claim_resolve,
                when=F["claim_found"] & F["reset_uncertain"],
            )
        ),
        Row(SwitchTo(I18nFormat("btn-back.general"), id="back", state=DashboardEarning.CLAIMS)),
        IgnoreUpdate(),
        state=DashboardEarning.CLAIM,
        getter=admin_getter,
    ),
)
