from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from packaging.version import Version

from src.application.events import RemnawaveErrorEvent, RemnawaveVersionWarningEvent
from src.core.constants import REMNAWAVE_MAX_VERSION, REMNAWAVE_V3_MAX_VERSION
from src.core.utils.panel_identity import PanelApiVersionMismatchError
from src.lifespan import _check_remnawave_connection


@pytest.mark.parametrize(
    ("api_version", "panel_version", "warn"),
    [
        (3, "3.4.5", False),
        (3, "3.4.7", False),
        (3, "3.4.99", False),
        (3, "3.5.0", True),
        (2, "2.8.1", False),
        (2, "2.8.2", True),
    ],
)
async def test_warning_uses_active_adapter_and_ignores_v3_patch_updates(
    api_version: int, panel_version: str, warn: bool
) -> None:
    service = SimpleNamespace(
        api_version=api_version, try_connection=AsyncMock(return_value=Version(panel_version))
    )
    event_bus = SimpleNamespace(publish=AsyncMock())
    config = SimpleNamespace(build=SimpleNamespace(data={}))

    await _check_remnawave_connection(service, config, event_bus)

    service.try_connection.assert_awaited_once()
    if not warn:
        event_bus.publish.assert_not_awaited()
        return
    event_bus.publish.assert_awaited_once()
    event = event_bus.publish.await_args.args[0]
    assert isinstance(event, RemnawaveVersionWarningEvent)
    assert event.panel_version == panel_version
    expected = REMNAWAVE_V3_MAX_VERSION if api_version == 3 else REMNAWAVE_MAX_VERSION
    assert event.as_payload().i18n_kwargs["max_version"] == str(expected)


async def test_actual_connection_failure_still_publishes_error() -> None:
    failure = RuntimeError("Invalid v3 response")
    service = SimpleNamespace(try_connection=AsyncMock(side_effect=failure))
    event_bus = SimpleNamespace(publish=AsyncMock())

    await _check_remnawave_connection(
        service, SimpleNamespace(build=SimpleNamespace(data={})), event_bus
    )

    event = event_bus.publish.await_args.args[0]
    assert isinstance(event, RemnawaveErrorEvent)
    assert event.exception is failure


async def test_wrong_api_major_still_aborts_startup() -> None:
    failure = PanelApiVersionMismatchError("The v3 client requires panel 3.x")
    service = SimpleNamespace(try_connection=AsyncMock(side_effect=failure))
    event_bus = SimpleNamespace(publish=AsyncMock())

    with pytest.raises(PanelApiVersionMismatchError):
        await _check_remnawave_connection(
            service, SimpleNamespace(build=SimpleNamespace(data={})), event_bus
        )

    assert isinstance(event_bus.publish.await_args.args[0], RemnawaveErrorEvent)
