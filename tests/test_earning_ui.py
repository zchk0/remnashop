from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.enums import ButtonStyle, ContentType
from fluent_compiler.bundle import FluentBundle
from fluentogram.translator import FluentTranslator

from src.application.dto import PlanDto, SettingsDto, UserDto
from src.application.dto.earning import ChannelTaskDto, EarningStatisticsDto
from src.application.use_cases.earning.channels import EarningChannelsDto
from src.core.constants import CONFIG_KEY, CONTAINER_KEY, USER_KEY
from src.core.enums import BannerName, Locale, Role
from src.telegram.routers.dashboard.earning.dialog import router as admin_dialog
from src.telegram.routers.dashboard.earning.getters import admin_getter, channels_getter
from src.telegram.routers.dashboard.earning.handlers import on_plan_select
from src.telegram.routers.earning.dialog import router as user_dialog
from src.telegram.routers.earning.handlers import on_task_select
from src.telegram.routers.menu.dialog import custom_buttons, menu
from src.telegram.states import DashboardEarning, Earning
from src.telegram.widgets.banner import get_banner


@pytest.mark.parametrize("color", [None, *ButtonStyle])
@pytest.mark.parametrize("available", [True, False])
async def test_earning_menu_button_is_full_width_after_custom_buttons(color, available):
    rows = menu.keyboard.buttons
    earning_row = next(row for row in rows if row.find("earning_success") is not None)
    dashboard_row = next(row for row in rows if row.find("dashboard") is not None)
    assert rows.index(custom_buttons[-1]) < rows.index(earning_row) < rows.index(dashboard_row)
    keyboard = await earning_row.render_keyboard(
        {
            "earning_available": available,
            "earning_color": color,
            "earning_text": "Бесплатные дни",
        },
        SimpleNamespace(is_preview=lambda: False),
    )
    if available:
        assert len(keyboard) == 1 and len(keyboard[0]) == 1
        assert keyboard[0][0].text == "Бесплатные дни"
        assert keyboard[0][0].style == color
    else:
        assert not keyboard


async def test_user_can_select_task_and_admin_can_select_trial_plan():
    manager = SimpleNamespace(dialog_data={}, switch_to=AsyncMock())
    await on_task_select(None, None, manager, "42")
    assert manager.dialog_data["task_id"] == 42
    manager.switch_to.assert_awaited_with(Earning.TASK)
    manager.dialog_data.update(input_field="trial_plan_id", task={})
    manager.middleware_data = {USER_KEY: UserDto(name="Admin", role=Role.ADMIN)}
    await on_plan_select(None, None, manager, "7")
    assert manager.dialog_data["task"]["trial_plan_id"] == 7
    manager.switch_to.assert_awaited_with(DashboardEarning.TASK)


async def test_all_user_and_admin_windows_render_with_real_translations():
    translator = FluentTranslator(
        locale="ru",
        translator=FluentBundle.from_string(
            locale="ru",
            text="\n".join(
                path.read_text("utf-8")
                for path in sorted(Path("assets/translations/ru").glob("*.ftl"))
            ),
            use_isolating=False,
        ),
    )
    context = SimpleNamespace(widget_data={})
    task = ChannelTaskDto(id=1, title="Test", channel_url="https://t.me/test", channel_id=-100123)
    manager = SimpleNamespace(
        dialog_data={"task": asdict(task)},
        is_preview=lambda: False,
        current_context=lambda: context,
        middleware_data={
            USER_KEY: UserDto(name="Admin", role=Role.ADMIN),
            CONTAINER_KEY: SimpleNamespace(get=AsyncMock(return_value=translator)),
        },
    )
    data = await admin_getter.__dishka_orig_func__(
        dialog_manager=manager,
        earning_dao=SimpleNamespace(
            list_tasks=AsyncMock(return_value=[task]),
            get_pending_claims=AsyncMock(return_value=[]),
        ),
        settings_dao=SimpleNamespace(get=AsyncMock(return_value=SettingsDto())),
        plan_dao=SimpleNamespace(get_all=AsyncMock(return_value=[PlanDto(id=1, name="Paid")])),
        i18n=translator,
    )
    data.update(
        tasks=[{"id": 1, "label": "Channel"}],
        has_tasks=True,
        task_available=True,
        allowed=True,
        support_url="https://t.me/support",
    )
    for dialog in (admin_dialog, user_dialog):
        for window in dialog.windows.values():
            window_data = data
            if window.state == DashboardEarning.CHANNELS:
                window_data = await channels_getter.__dishka_orig_func__(
                    dialog_manager=manager,
                    get_channels=AsyncMock(
                        return_value=EarningChannelsDto(
                            tasks=[task],
                            statistics=EarningStatisticsDto(
                                daily=2,
                                weekly=4,
                                monthly=8,
                                total=16,
                                active_tasks=1,
                            ),
                        )
                    ),
                )
            text = await window.render_text(window_data, manager)
            assert text and len(text) <= 4096
            keyboard = await window.keyboard.render_keyboard(window_data, manager)
            assert keyboard
            for row in keyboard:
                for button in row:
                    assert button.text and not button.text.startswith("btn-")
    for field in (
        "channel",
        "title",
        "days",
        "discount",
        "max-claims",
        "trial-days",
        "allowed-telegram-ids",
        "button-text",
        "subscriber-price",
    ):
        data["input_key"] = "msg-earning-input-" + field
        assert await admin_dialog.windows[DashboardEarning.INPUT].render_text(data, manager)


def test_channels_are_on_a_separate_admin_tab():
    main = admin_dialog.windows[DashboardEarning.MAIN]
    channels = admin_dialog.windows[DashboardEarning.CHANNELS]
    assert main.keyboard.find("channels").state == DashboardEarning.CHANNELS
    assert main.keyboard.find("create") is None
    assert main.keyboard.find("task_scroll") is None
    assert channels.keyboard.find("create") is not None
    assert channels.keyboard.find("task_scroll") is not None
    assert channels.keyboard.find("back").state == DashboardEarning.MAIN
    assert admin_dialog.windows[DashboardEarning.TASK].keyboard.find("back").state == (
        DashboardEarning.CHANNELS
    )


def test_earning_banner_reuses_menu_until_replaced_and_keeps_other_sections_unchanged(tmp_path):
    banners = tmp_path / "user"
    defaults = tmp_path / "defaults"
    locale_dir = banners / "ru"
    locale_dir.mkdir(parents=True)
    menu_banner = locale_dir / "menu.jpg"
    menu_banner.touch()
    default_banner = banners / "default.jpg"
    default_banner.touch()

    def resolve(name):
        return get_banner(banners, defaults, name, Locale.RU, Locale.RU)

    try:
        assert resolve(BannerName.EARNING) == resolve(BannerName.MENU)
        assert resolve(BannerName.DEVICES)[0] == default_banner
        custom = locale_dir / "earning.png"
        custom.touch()
        get_banner.cache_clear()  # Restarting the bot clears its in-memory caches.
        assert resolve(BannerName.EARNING) == (custom, ContentType.PHOTO)
        assert resolve(BannerName.MENU)[0] == menu_banner
    finally:
        get_banner.cache_clear()


@pytest.mark.parametrize("enabled", [True, False])
async def test_earning_windows_render_banner_using_the_global_banner_setting(tmp_path, enabled):
    (tmp_path / "default.jpg").touch()
    manager = SimpleNamespace(
        middleware_data={
            USER_KEY: UserDto(name="Test", language=Locale.RU),
            CONFIG_KEY: SimpleNamespace(
                bot=SimpleNamespace(use_banners=enabled),
                banners_dir=tmp_path,
                default_banners_dir=tmp_path / "defaults",
                default_locale=Locale.RU,
            ),
        }
    )
    try:
        for window in user_dialog.windows.values():
            media = await window.render_media({}, manager)
            if enabled:
                assert media.path == tmp_path / "default.jpg"
                assert media.type == ContentType.PHOTO
            else:
                assert media is None
    finally:
        get_banner.cache_clear()
