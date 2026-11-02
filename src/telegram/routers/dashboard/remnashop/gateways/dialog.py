from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.text import Format
from magic_filter import F

from src.core.enums import BannerName, Currency
from src.telegram.keyboards import main_menu_button
from src.telegram.states import DashboardRemnashop, RemnashopGateways
from src.telegram.widgets import Banner, I18nFormat, IgnoreUpdate
from src.telegram.widgets.kbd import (
    Button,
    Column,
    CopyText,
    Group,
    ListGroup,
    Row,
    ScrollingGroup,
    Select,
    Start,
    SwitchTo,
)

from .flippay_methods import (
    flippay_methods_getter,
    on_flippay_method_name_input,
    on_flippay_method_name_reset,
    on_flippay_method_select,
    on_flippay_method_toggle,
    on_flippay_methods_refresh,
)
from .getters import (
    currency_getter,
    field_getter,
    gateway_getter,
    gateways_getter,
    placement_getter,
)
from .handlers import (
    on_active_toggle,
    on_autopay_toggle,
    on_default_currency_select,
    on_field_input,
    on_field_reset,
    on_field_select,
    on_gateway_move,
    on_gateway_select,
    on_gateway_test,
)

gateways = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-gateways-main"),
    ScrollingGroup(
        ListGroup(
            Row(
                Button(
                    text=I18nFormat("btn-gateway.title", gateway_type=F["item"]["gateway_type"]),
                    id="select_gateway",
                    on_click=on_gateway_select,
                ),
                Button(
                    text=I18nFormat("btn-gateway.test"),
                    id="test_gateway",
                    on_click=on_gateway_test,
                ),
                Button(
                    text=I18nFormat("btn-gateway.active-toggle", is_active=F["item"]["is_active"]),
                    id="active_toggle",
                    on_click=on_active_toggle,
                ),
            ),
            id="gateways_list",
            item_id_getter=lambda item: item["id"],
            items="gateways",
        ),
        id="scroll",
        width=3,
        height=7,
        hide_on_single_page=True,
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-gateway.placement"),
            id="placement",
            state=RemnashopGateways.PLACEMENT,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-gateway.default-currency"),
            id="default_currency",
            state=RemnashopGateways.CURRENCY,
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardRemnashop.MAIN,
            mode=StartMode.RESET_STACK,
        ),
        *main_menu_button,
    ),
    IgnoreUpdate(),
    state=RemnashopGateways.MAIN,
    getter=gateways_getter,
)

gateway_settings = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-gateways-settings", gateway_type=F["gateway_type"]),
    I18nFormat("msg-gateways-autopay-note", F["has_autopay"]),
    SwitchTo(
        text=I18nFormat("btn-flippay-methods"),
        id="flippay_methods",
        state=RemnashopGateways.FLIPPAY_METHODS,
        when=F["is_flippay"],
    ),
    Row(
        Button(
            text=I18nFormat("btn-gateway-autopay-toggle", enabled=F["autopay_enabled"]),
            id="autopay_toggle",
            on_click=on_autopay_toggle,
            when=F["has_autopay"],
        ),
    ),
    Row(
        Select(
            text=I18nFormat("btn-gateway.display-name"),
            id="display_name_setting",
            item_id_getter=lambda item: item["field"],
            items="display_name_field",
            type_factory=str,
            on_click=on_field_select,
        ),
    ),
    Group(
        Select(
            text=I18nFormat(
                "btn-gateway.setting",
                field=F["item"]["field"].upper(),
                timeout_minutes=F["item"]["value"],
            ),
            id="setting",
            item_id_getter=lambda item: item["field"],
            items="settings",
            type_factory=str,
            on_click=on_field_select,
        ),
        width=2,
    ),
    Row(
        CopyText(
            text=I18nFormat("btn-gateway.webhook-copy"),
            copy_text=Format("{webhook}"),
        ),
        when=F["requires_webhook"],
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopGateways.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopGateways.SETTINGS,
    getter=gateway_getter,
)

gateway_field = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-gateways-field", gateway_type=F["gateway_type"]),
    Row(
        Button(
            text=I18nFormat("btn-gateway.field-reset"),
            id="field_reset",
            on_click=on_field_reset,
            when=~F["is_empty"],
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopGateways.SETTINGS,
        ),
    ),
    MessageInput(func=on_field_input),
    IgnoreUpdate(),
    state=RemnashopGateways.FIELD,
    getter=field_getter,
)

default_currency = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-gateways-default-currency"),
    Column(
        Select(
            text=I18nFormat(
                "btn-gateway.default-currency-choice",
                symbol=F["item"]["symbol"],
                currency=F["item"]["currency"],
                enabled=F["item"]["enabled"],
            ),
            id="currency",
            item_id_getter=lambda item: item["currency"],
            items="currency_list",
            type_factory=Currency,
            on_click=on_default_currency_select,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopGateways.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopGateways.CURRENCY,
    getter=currency_getter,
)

placement = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-gateways-placement"),
    ListGroup(
        Row(
            Button(
                text=I18nFormat("btn-gateway.title", gateway_type=F["item"]["gateway_type"]),
                id="gateway",
            ),
            Button(
                text=Format("🔼"),
                id="move",
                on_click=on_gateway_move,
            ),
        ),
        id="gateways_list",
        item_id_getter=lambda item: item["id"],
        items="gateways",
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopGateways.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopGateways.PLACEMENT,
    getter=placement_getter,
)

flippay_methods = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-flippay-methods"),
    Column(
        Select(
            text=Format("{item[status]} {item[title]}"),
            id="flippay_method",
            item_id_getter=lambda item: item["id"],
            items="methods",
            type_factory=int,
            on_click=on_flippay_method_select,
        ),
    ),
    Button(
        text=I18nFormat("btn-flippay-methods-refresh"),
        id="flippay_refresh",
        on_click=on_flippay_methods_refresh,
    ),
    SwitchTo(text=I18nFormat("btn-back.general"), id="back", state=RemnashopGateways.SETTINGS),
    IgnoreUpdate(),
    state=RemnashopGateways.FLIPPAY_METHODS,
    getter=flippay_methods_getter,
)

flippay_method = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-flippay-method"),
    Button(
        text=I18nFormat("btn-flippay-method-toggle"),
        id="flippay_method_toggle",
        on_click=on_flippay_method_toggle,
        when=F["available"] | F["enabled"],
    ),
    SwitchTo(
        text=I18nFormat("btn-gateway.display-name"),
        id="flippay_method_name",
        state=RemnashopGateways.FLIPPAY_METHOD_NAME,
    ),
    SwitchTo(
        text=I18nFormat("btn-back.general"), id="back", state=RemnashopGateways.FLIPPAY_METHODS
    ),
    IgnoreUpdate(),
    state=RemnashopGateways.FLIPPAY_METHOD,
    getter=flippay_methods_getter,
)

flippay_method_name = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-flippay-method-name"),
    MessageInput(on_flippay_method_name_input),
    Button(
        text=I18nFormat("btn-gateway.field-reset"),
        id="flippay_name_reset",
        on_click=on_flippay_method_name_reset,
    ),
    SwitchTo(
        text=I18nFormat("btn-back.general"), id="back", state=RemnashopGateways.FLIPPAY_METHOD
    ),
    IgnoreUpdate(),
    state=RemnashopGateways.FLIPPAY_METHOD_NAME,
    getter=flippay_methods_getter,
)

router = Dialog(
    gateways,
    gateway_settings,
    gateway_field,
    default_currency,
    placement,
    flippay_methods,
    flippay_method,
    flippay_method_name,
)
