from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import AnswerCallbackQuery
from aiogram.types import CallbackQuery, Update
from aiogram.types import User as AiogramUser
from aiogram_dialog.api.exceptions import (
    InvalidStackIdError,
    OutdatedIntent,
    UnknownIntent,
    UnknownState,
)

from src.application.common import BotService, EventPublisher, Notifier
from src.application.common.dao import UserDao
from src.application.dto import UserDto
from src.application.use_cases.misc.commands.navigation import RedirectMenu
from src.core.constants import CONFIG_KEY, CONTAINER_KEY
from src.core.enums import Role
from src.telegram.middlewares.error import ErrorMiddleware, _find_remnawave_transport_error


def _connect_timeout(url: str) -> httpx.ConnectTimeout:
    return httpx.ConnectTimeout(
        "Connection timed out",
        request=httpx.Request("GET", url),
    )


def test_finds_transport_error_for_remnawave_host() -> None:
    error = _connect_timeout("https://panel.example.com/api/users/123")

    result = _find_remnawave_transport_error(error, "https://panel.example.com")

    assert result is error


def test_ignores_transport_error_for_another_host() -> None:
    error = _connect_timeout("https://api.example.com/users/123")

    result = _find_remnawave_transport_error(error, "https://panel.example.com")

    assert result is None


def test_finds_wrapped_remnawave_transport_error() -> None:
    transport_error = _connect_timeout("http://remnawave:3000/api/users/123")
    error = RuntimeError("Could not render subscription")
    error.__cause__ = transport_error

    result = _find_remnawave_transport_error(error, "http://remnawave:3000")

    assert result is transport_error


def test_ignores_transport_error_without_request() -> None:
    error = httpx.ConnectTimeout("Connection timed out")

    result = _find_remnawave_transport_error(error, "https://panel.example.com")

    assert result is None


async def test_middleware_handles_remnawave_timeout_without_publishing_error() -> None:
    error = _connect_timeout("https://panel.example.com/api/users/123")
    event = SimpleNamespace(exception=error)
    aiogram_user = AiogramUser(id=123, is_bot=False, first_name="Test")

    notifier = AsyncMock()
    event_publisher = AsyncMock()
    dependencies = {
        BotService: AsyncMock(),
        EventPublisher: event_publisher,
        Notifier: notifier,
        RedirectMenu: AsyncMock(),
        UserDao: AsyncMock(),
    }
    container = AsyncMock()
    container.get.side_effect = lambda dependency: dependencies[dependency]
    config = SimpleNamespace(
        remnawave=SimpleNamespace(
            url=SimpleNamespace(get_secret_value=lambda: "https://panel.example.com")
        )
    )
    handler = AsyncMock()

    result = await ErrorMiddleware().middleware_logic(
        handler,
        event,
        {
            "event_from_user": aiogram_user,
            CONFIG_KEY: config,
            CONTAINER_KEY: container,
        },
    )

    assert result is None
    notifier.notify_user.assert_awaited_once()
    assert notifier.notify_user.await_args.kwargs["i18n_key"] == ("ntf-error.remnawave-unavailable")
    event_publisher.publish.assert_not_awaited()
    handler.assert_not_awaited()


def _context_error_case(exception, *, privileged=False):
    aiogram_user = AiogramUser(id=123, is_bot=False, first_name="Test")
    user = UserDto(id=7, telegram_id=123, name="Test", role=Role.ADMIN if privileged else Role.USER)
    notifier = AsyncMock()
    publisher = AsyncMock()
    redirect = SimpleNamespace(system=AsyncMock())
    user_dao = SimpleNamespace(get_by_telegram_id=AsyncMock(return_value=user))
    dependencies = {
        BotService: AsyncMock(),
        EventPublisher: publisher,
        Notifier: notifier,
        RedirectMenu: redirect,
        UserDao: user_dao,
    }
    container = SimpleNamespace(
        get=AsyncMock(side_effect=lambda dependency: dependencies[dependency])
    )
    config = SimpleNamespace(
        remnawave=SimpleNamespace(
            url=SimpleNamespace(get_secret_value=lambda: "https://panel.example.com"),
        )
    )
    data = {"event_from_user": aiogram_user, CONFIG_KEY: config, CONTAINER_KEY: container}
    callback = SimpleNamespace(answer=AsyncMock())
    event = SimpleNamespace(
        exception=exception,
        update=SimpleNamespace(
            message=None,
            callback_query=callback,
        ),
    )
    return SimpleNamespace(
        event=event,
        data=data,
        callback=callback,
        user=user,
        notifier=notifier,
        publisher=publisher,
        redirect=redirect,
    )


@pytest.mark.parametrize("privileged", [False, True])
@pytest.mark.parametrize(
    "exception",
    [
        UnknownIntent("Context not found for intent id: KDqh48"),
        UnknownState("Unknown dialog state"),
        InvalidStackIdError("Unknown stack"),
        OutdatedIntent("old-stack", "Outdated intent"),
    ],
)
async def test_context_loss_is_recovered_without_reraising_or_reporting(exception, privileged):
    case = _context_error_case(exception, privileged=privileged)
    # aiogram-dialog's default error handler reraises the original exception.
    handler = AsyncMock(side_effect=exception)
    result = await ErrorMiddleware().middleware_logic(handler, case.event, case.data)
    assert result is None
    case.callback.answer.assert_awaited_once()
    case.redirect.system.assert_awaited_once_with(123)
    key = "ntf-error.lost-context" if privileged else "ntf-error.lost-context-restart"
    case.notifier.notify_user.assert_awaited_once_with(case.user, i18n_key=key)
    case.publisher.publish.assert_not_awaited()
    handler.assert_not_awaited()


async def test_expired_callback_does_not_interrupt_context_recovery():
    case = _context_error_case(UnknownIntent("Old screen"))
    case.callback.answer.side_effect = TelegramBadRequest(
        method=AnswerCallbackQuery(callback_query_id="expired"),
        message="query is too old and response timeout expired",
    )
    await ErrorMiddleware().middleware_logic(AsyncMock(), case.event, case.data)
    case.redirect.system.assert_awaited_once_with(123)
    case.notifier.notify_user.assert_awaited_once()
    case.publisher.publish.assert_not_awaited()


async def test_dispatcher_handles_stale_callback_before_default_error_handler(monkeypatch):
    error = UnknownIntent("Context not found for intent id: KDqh48")
    case = _context_error_case(error)
    dispatcher = Dispatcher()
    ErrorMiddleware().setup_outer(dispatcher)

    async def load_missing_context(handler, event, data):
        raise error

    async def default_dialog_error_handler(event):
        raise event.exception

    dispatcher.callback_query.outer_middleware(load_missing_context)
    dispatcher.errors.register(default_dialog_error_handler)
    answer = AsyncMock(return_value=True)
    monkeypatch.setattr(CallbackQuery, "answer", answer)
    update = Update(
        update_id=1,
        callback_query=CallbackQuery(
            id="callback-1",
            from_user=case.data["event_from_user"],
            chat_instance="chat-1",
            data="KDqh48:button",
        ),
    )
    async with Bot("123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi") as bot:
        result = await dispatcher.feed_update(bot, update, **case.data)
    assert result is None
    answer.assert_awaited_once()
    case.redirect.system.assert_awaited_once_with(123)
    case.publisher.publish.assert_not_awaited()
