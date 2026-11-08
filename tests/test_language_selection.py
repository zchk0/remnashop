from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram_dialog import ShowMode, StartMode

from src.application.common import TranslatorHub
from src.application.dto import TelegramUserDto, UserDto
from src.application.use_cases.user.commands.language import SetUserLanguage
from src.application.use_cases.user.commands.registration import (
    UpdateUserProfile,
    UpdateUserProfileDto,
)
from src.core.config import AppConfig
from src.core.constants import CONTAINER_KEY, USER_KEY
from src.core.enums import Locale
from src.infrastructure.di.ioc import create_aiogram_container
from src.infrastructure.di.providers.retort import RetortProvider
from src.infrastructure.services.command import CommandService
from src.infrastructure.services.i18n import LayeredFileStorage
from src.infrastructure.services.translator import TranslatorHubImpl
from src.telegram.routers.extra.commands import on_language_command
from src.telegram.routers.menu.dialog import language as language_window
from src.telegram.routers.menu.getters import language_getter
from src.telegram.routers.menu.handlers import on_language_selected
from src.telegram.states import MainMenu


@pytest.fixture(scope="module")
def hub(tmp_path_factory):
    return TranslatorHubImpl(
        {Locale.RU: (Locale.RU,), Locale.EN: (Locale.EN, Locale.RU)},
        root_locale=Locale.RU,
        storage=LayeredFileStorage(
            user_translations_dir=Path("assets/translations"),
            default_translations_dir=tmp_path_factory.mktemp("language") / "missing",
        ),
        retort=RetortProvider().get_retort(),
    )


def user(language=Locale.RU, manual=False):
    return TelegramUserDto(
        id=1, telegram_id=123, name="User", language=language, is_language_manual=manual
    )


def language_service(saved_user, *, locales=(Locale.RU, Locale.EN)):
    uow = AsyncMock()
    dao = SimpleNamespace(
        get_by_id=AsyncMock(return_value=saved_user),
        update=AsyncMock(side_effect=lambda updated: replace(updated)),
    )
    config = SimpleNamespace(locales=list(locales))
    return SetUserLanguage(uow, dao, config), dao, uow, config


async def test_language_command_follows_tasks_and_opens_selection(hub):
    bot = SimpleNamespace(set_my_commands=AsyncMock(return_value=True))
    config = SimpleNamespace(
        locales=[Locale.RU, Locale.EN],
        default_locale=Locale.RU,
        bot=SimpleNamespace(setup_commands=True),
    )
    await CommandService(bot, config, hub).setup_commands()
    for call in bot.set_my_commands.await_args_list:
        commands = call.kwargs["commands"]
        names = [command.command for command in commands]
        assert names[names.index("tasks") + 1] == "language"
        language = commands[names.index("language")]
        assert language.description == (
            "Change language" if call.kwargs["language_code"] == Locale.EN else "Выбрать язык"
        )

    manager = SimpleNamespace(start=AsyncMock())
    await on_language_command(None, user(), manager)
    manager.start.assert_awaited_once_with(
        state=MainMenu.LANGUAGE,
        mode=StartMode.RESET_STACK,
        show_mode=ShowMode.DELETE_AND_SEND,
    )


def test_russian_and_english_are_enabled_by_default():
    assert AppConfig.model_fields["locales"].default == [Locale.RU, Locale.EN]


@pytest.mark.parametrize(
    ("initial", "choice"),
    [(Locale.RU, Locale.RU), (Locale.RU, Locale.EN), (Locale.EN, Locale.RU)],
)
async def test_manual_choice_survives_next_telegram_profile_update(initial, choice):
    actor = user(initial)
    service, dao, uow, config = language_service(replace(actor))
    updated = await service(actor, choice)
    assert updated.language == choice
    assert updated.is_language_manual is True
    assert set(dao.update.await_args.args[0].changed_data) >= {"is_language_manual"}
    uow.commit.assert_awaited_once()

    # Simulate loading the persisted profile for a later Telegram request.
    reloaded = replace(updated)
    telegram_language = Locale.EN if choice == Locale.RU else Locale.RU
    update_profile = UpdateUserProfile(uow, dao, config)
    result = await update_profile.system(
        UpdateUserProfileDto(
            user=reloaded,
            username="new_username",
            full_name=reloaded.name,
            language_code=telegram_language,
            telegram_id=reloaded.telegram_id,
        )
    )
    assert result.language == choice
    assert result.is_language_manual is True
    assert result.username == "new_username"


async def test_language_still_follows_telegram_before_manual_selection():
    actor = user()
    _, dao, uow, config = language_service(actor)
    result = await UpdateUserProfile(uow, dao, config).system(
        UpdateUserProfileDto(
            user=actor,
            username=None,
            full_name=actor.name,
            language_code="en",
            telegram_id=actor.telegram_id,
        )
    )
    assert result.language == Locale.EN
    assert result.is_language_manual is False
    uow.commit.assert_awaited_once()


async def test_disallowed_locale_cannot_be_saved():
    service, dao, uow, _ = language_service(user(), locales=(Locale.RU,))
    with pytest.raises(ValueError, match="Unsupported language"):
        await service(user(), Locale.EN)
    dao.get_by_id.assert_not_awaited()
    dao.update.assert_not_awaited()
    uow.commit.assert_not_awaited()


async def test_failed_save_does_not_commit():
    service, dao, uow, _ = language_service(user())
    dao.update.side_effect = None
    dao.update.return_value = None
    with pytest.raises(ValueError, match="Could not update language"):
        await service(user(), Locale.EN)
    uow.commit.assert_not_awaited()


async def test_selection_redraws_immediately_in_chosen_language(hub):
    service, _, _, config = language_service(user())
    callback = SimpleNamespace(answer=AsyncMock())
    # A translator may already be cached earlier in this request. The language
    # screen must still render the new locale immediately after selection.
    manager = SimpleNamespace(
        middleware_data={
            USER_KEY: user(),
            CONTAINER_KEY: SimpleNamespace(
                get=AsyncMock(return_value=hub.get_translator_by_locale(Locale.RU))
            ),
        },
        is_preview=lambda: False,
        current_context=lambda: SimpleNamespace(widget_data={}),
    )
    await on_language_selected.__dishka_orig_func__(
        callback, None, manager, "en", config, service, hub
    )
    selected = manager.middleware_data[USER_KEY]
    assert isinstance(selected, TelegramUserDto)
    assert selected.language == Locale.EN
    assert selected.is_language_manual

    data = await language_getter.__dishka_orig_func__(selected, config, hub)
    assert data["languages"] == [
        {"locale": "ru", "label": "Русский"},
        {"locale": "en", "label": "✅ English"},
    ]
    text = await language_window.text.render_text(data, manager)
    keyboard = await language_window.keyboard.render_keyboard(data, manager)
    assert "Choose your interface language" in text
    assert keyboard[-1][0].text == "↩️ Main menu"
    callback.answer.assert_awaited_once_with()


@pytest.mark.parametrize("item_id", ["de", "invalid", "en"])
async def test_forged_or_disabled_selection_is_rejected(hub, item_id):
    set_language = AsyncMock()
    callback = SimpleNamespace(answer=AsyncMock())
    manager = SimpleNamespace(middleware_data={USER_KEY: user()})
    config = SimpleNamespace(locales=[Locale.RU])
    await on_language_selected.__dishka_orig_func__(
        callback, None, manager, item_id, config, set_language, hub
    )
    set_language.assert_not_awaited()
    assert manager.middleware_data[USER_KEY].language == Locale.RU
    assert callback.answer.await_args.kwargs == {"show_alert": True}


async def test_language_options_follow_configured_locales(hub):
    data = await language_getter.__dishka_orig_func__(
        user(), SimpleNamespace(locales=[Locale.RU]), hub
    )
    assert data["languages"] == [{"locale": "ru", "label": "✅ Русский"}]


@pytest.mark.parametrize("locale", [Locale.RU, Locale.EN])
async def test_language_window_loads_with_dispatcher_config_and_dishka(hub, locale):
    config = SimpleNamespace(locales=[Locale.RU, Locale.EN])
    dependencies = {AppConfig: config, TranslatorHub: hub}
    container = SimpleNamespace(
        get=AsyncMock(side_effect=lambda dependency, **kwargs: dependencies[dependency])
    )
    manager = SimpleNamespace(
        middleware_data={"config": config, USER_KEY: user(locale), CONTAINER_KEY: container},
        is_preview=lambda: False,
    )
    manager.middleware_data["dialog_manager"] = manager
    dialog = SimpleNamespace(load_data=AsyncMock(return_value={}))

    data = await language_window.load_data(dialog, manager)
    text = await language_window.text.render_text(data, manager)
    keyboard = await language_window.keyboard.render_keyboard(data, manager)

    assert data["languages"] == [
        {"locale": "ru", "label": f"{'✅ ' if locale == Locale.RU else ''}Русский"},
        {"locale": "en", "label": f"{'✅ ' if locale == Locale.EN else ''}English"},
    ]
    assert text == hub.get_translator_by_locale(locale).get("msg-language-select")
    assert keyboard[-1][0].text == hub.get_translator_by_locale(locale).get("btn-back.menu")


def test_telegram_user_conversion_preserves_manual_choice():
    converted = TelegramUserDto.from_user(
        UserDto(id=1, telegram_id=123, name="User", language=Locale.EN, is_language_manual=True)
    )
    assert converted.language == Locale.EN
    assert converted.is_language_manual is True


async def test_aiogram_dependency_graph_accepts_language_use_case():
    container = create_aiogram_container(AppConfig.get(), None)
    await container.close()
