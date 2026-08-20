from typing import Optional
from unittest.mock import AsyncMock

from src.application.dto.device import LinkedDeviceDto
from src.application.services.device_binding import bind_linked_device


class _FakeLinkedDeviceDao:
    """Minimal LinkedDeviceDao stub.

    ``stale_rows`` models the real-world state this suite is about: rows that
    linger in linked_devices after their panel HWID is gone, because deleting a
    device in the bot only clears the panel side.
    """

    def __init__(self, stale_rows: int, existing: Optional[LinkedDeviceDto] = None) -> None:
        self.stale_rows = stale_rows
        self.existing = existing
        self.lock_binding_by_telegram_id = AsyncMock()
        self.upsert = AsyncMock(side_effect=lambda device: device)

    async def get_by_device_id(self, device_id: str) -> Optional[LinkedDeviceDto]:
        return self.existing

    async def count_by_telegram_id(
        self, telegram_id: int, exclude_device_id: Optional[str] = None
    ) -> int:
        return self.stale_rows


async def test_limit_counts_panel_devices_not_local_rows() -> None:
    """An account under its panel limit must be able to link a new device.

    linked_devices had accumulated far more rows than the subscription allows,
    which blocked every new device even though the panel held only three.
    """
    dao = _FakeLinkedDeviceDao(stale_rows=15)

    result = await bind_linked_device(
        dao,
        device_id="new-tv",
        telegram_id=1,
        device_limit=15,
        panel_user_uuid="panel-uuid",
        short_uuid="short-uuid",
        panel_device_ids=["phone", "desktop", "tablet"],
    )

    assert result.is_bound
    dao.upsert.assert_awaited_once()


async def test_limit_is_enforced_from_panel_devices() -> None:
    dao = _FakeLinkedDeviceDao(stale_rows=0)

    result = await bind_linked_device(
        dao,
        device_id="new-tv",
        telegram_id=1,
        device_limit=3,
        panel_user_uuid="panel-uuid",
        short_uuid="short-uuid",
        panel_device_ids=["phone", "desktop", "tablet"],
    )

    assert not result.is_bound
    assert result.device_limit == 3
    dao.upsert.assert_not_awaited()


async def test_device_already_on_panel_does_not_count_against_itself() -> None:
    """Re-linking a device that already holds a panel slot must not be refused."""
    existing = LinkedDeviceDto(device_id="tv", telegram_id=1)
    dao = _FakeLinkedDeviceDao(stale_rows=0, existing=existing)

    result = await bind_linked_device(
        dao,
        device_id="tv",
        telegram_id=1,
        device_limit=3,
        panel_user_uuid="panel-uuid",
        short_uuid="short-uuid",
        panel_device_ids=["phone", "desktop", "tv"],
    )

    assert result.is_bound


async def test_stale_local_link_does_not_bypass_full_panel_limit() -> None:
    """A deleted panel HWID may still look linked in the local table."""
    existing = LinkedDeviceDto(device_id="old-tv", telegram_id=1)
    dao = _FakeLinkedDeviceDao(stale_rows=1, existing=existing)

    result = await bind_linked_device(
        dao,
        device_id="old-tv",
        telegram_id=1,
        device_limit=3,
        panel_user_uuid="panel-uuid",
        short_uuid="short-uuid",
        panel_device_ids=["phone", "desktop", "tablet"],
    )

    assert not result.is_bound
    assert result.device_limit == 3
    dao.upsert.assert_not_awaited()


async def test_falls_back_to_local_rows_when_panel_unavailable() -> None:
    """Without panel data the local table stays the safety net."""
    dao = _FakeLinkedDeviceDao(stale_rows=15)

    result = await bind_linked_device(
        dao,
        device_id="new-tv",
        telegram_id=1,
        device_limit=15,
        panel_user_uuid="panel-uuid",
        short_uuid="short-uuid",
        panel_device_ids=None,
    )

    assert not result.is_bound


async def test_unlimited_subscription_is_never_refused() -> None:
    dao = _FakeLinkedDeviceDao(stale_rows=0)

    result = await bind_linked_device(
        dao,
        device_id="new-tv",
        telegram_id=1,
        device_limit=0,
        panel_user_uuid="panel-uuid",
        short_uuid="short-uuid",
        panel_device_ids=["a", "b", "c", "d"],
    )

    assert result.is_bound
