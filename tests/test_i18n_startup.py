import asyncio
import importlib
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from adaptix import Retort
from dishka import make_async_container
from taskiq import TaskiqEvents, TaskiqState
from taskiq_redis import RedisStreamBroker

from src.application.common import EventSubscriber, TranslatorHub
from src.core.config import AppConfig
from src.core.enums import Locale
from src.infrastructure.di.providers.i18n import I18nProvider
from src.infrastructure.services import NotificationWorker, TranslatorHubImpl
from src.infrastructure.services.i18n import LayeredFileStorage


@pytest.fixture
def translation_config(tmp_path: Path) -> SimpleNamespace:
    user_dir = tmp_path / "user"
    default_dir = tmp_path / "default"
    for locale in ("ru", "en"):
        locale_dir = default_dir / locale
        locale_dir.mkdir(parents=True)
        (locale_dir / "messages.ftl").write_text(f"probe = {locale} default\n", encoding="utf-8")
    (user_dir / "en").mkdir(parents=True)
    (user_dir / "en" / "custom.ftl").write_text("probe = en custom\n", encoding="utf-8")
    return SimpleNamespace(
        translations_dir=user_dir,
        default_translations_dir=default_dir,
        locales=[Locale.RU, Locale.EN],
        default_locale=Locale.RU,
    )


async def test_slow_translation_loading_leaves_event_loop_available_and_loads_once(
    monkeypatch: pytest.MonkeyPatch, translation_config: SimpleNamespace
) -> None:
    loading_started = Event()
    release_loading = Event()

    def blocking_storage(**kwargs):
        loading_started.set()
        if not release_loading.wait(timeout=5):
            raise TimeoutError("Translation loading blocked the event loop")
        return LayeredFileStorage(**kwargs)

    storage_factory = Mock(side_effect=blocking_storage)
    monkeypatch.setattr("src.infrastructure.di.providers.i18n.LayeredFileStorage", storage_factory)
    container = make_async_container(
        I18nProvider(), context={AppConfig: translation_config, Retort: Retort()}
    )
    loading = asyncio.gather(container.get(TranslatorHub), container.get(TranslatorHubImpl))
    try:
        assert await asyncio.to_thread(loading_started.wait, 5)
        # The event loop must run this coroutine while file loading is still blocked.
        assert not loading.done()
        release_loading.set()
        hub, alias_hub = await loading

        assert hub is alias_hub
        storage_factory.assert_called_once()
        assert hub.get_translator_by_locale(Locale.RU).get("probe") == "ru default"
        assert hub.get_translator_by_locale(Locale.EN).get("probe") == "en custom"
    finally:
        release_loading.set()
        await asyncio.gather(loading, return_exceptions=True)
        await container.close()


@pytest.fixture
def worker_startup(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    module = importlib.import_module("src.infrastructure.taskiq.worker")
    broker = RedisStreamBroker("redis://localhost:6379/0")
    event_bus = SimpleNamespace(set_container_factory=Mock(), autodiscover=Mock())
    notifications = SimpleNamespace(set_container_factory=Mock())
    container = SimpleNamespace(get=AsyncMock())
    monkeypatch.setattr(module, "broker", broker)
    monkeypatch.setattr(module, "setup_logger", Mock())
    monkeypatch.setattr(module, "get_dispatcher", Mock())
    monkeypatch.setattr(module, "get_bg_manager_factory", Mock())
    monkeypatch.setattr(module, "setup_worker_dispatcher", Mock())
    monkeypatch.setattr(module, "create_taskiq_container", Mock(return_value=container))
    monkeypatch.setattr(module, "setup_taskiq_dishka", Mock())
    monkeypatch.setattr(module, "setup_aiogram_dishka", Mock())
    module.worker()
    return SimpleNamespace(
        start=broker.event_handlers[TaskiqEvents.WORKER_STARTUP][0],
        container=container,
        event_bus=event_bus,
        notifications=notifications,
    )


async def test_worker_finishes_loading_translations_before_starting_services(
    worker_startup: SimpleNamespace,
) -> None:
    translations_ready = False

    async def resolve(dependency):
        nonlocal translations_ready
        if dependency is TranslatorHub:
            await asyncio.sleep(0)
            translations_ready = True
            return Mock()
        assert translations_ready, "Worker services started before translations were ready"
        return {
            EventSubscriber: worker_startup.event_bus,
            NotificationWorker: worker_startup.notifications,
        }[dependency]

    worker_startup.container.get.side_effect = resolve

    await worker_startup.start(TaskiqState())

    assert translations_ready
    worker_startup.event_bus.autodiscover.assert_called_once()
    worker_startup.notifications.set_container_factory.assert_called_once()


async def test_worker_does_not_start_services_if_translation_loading_fails(
    worker_startup: SimpleNamespace,
) -> None:
    async def resolve(dependency):
        if dependency is TranslatorHub:
            raise OSError("Translation files unavailable")
        return {
            EventSubscriber: worker_startup.event_bus,
            NotificationWorker: worker_startup.notifications,
        }[dependency]

    worker_startup.container.get.side_effect = resolve

    with pytest.raises(OSError, match="Translation files unavailable"):
        await worker_startup.start(TaskiqState())

    worker_startup.event_bus.autodiscover.assert_not_called()
    worker_startup.notifications.set_container_factory.assert_not_called()
