from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from aiogram.types import User as AiogramUser

from src.application.common import BotService, EventPublisher, Notifier
from src.application.common.dao import UserDao
from src.application.use_cases.misc.commands.navigation import RedirectMenu
from src.core.constants import CONFIG_KEY, CONTAINER_KEY
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
    assert notifier.notify_user.await_args.kwargs["i18n_key"] == (
        "ntf-error.remnawave-unavailable"
    )
    event_publisher.publish.assert_not_awaited()
    handler.assert_not_awaited()
