from dataclasses import dataclass, replace
from typing import Optional

from src.application.common.dao.device import LinkedDeviceDao
from src.application.dto.device import LinkedDeviceDto


@dataclass(frozen=True)
class DeviceBindingResult:
    is_bound: bool
    device: Optional[LinkedDeviceDto] = None
    device_limit: int = 0
    message: Optional[str] = None


def _is_device_limit_reached(linked_count: int, device_limit: int) -> bool:
    return device_limit > 0 and linked_count >= device_limit


async def bind_linked_device(
    device_dao: LinkedDeviceDao,
    *,
    device_id: str,
    telegram_id: int,
    device_limit: int,
    panel_user_uuid: Optional[str],
    short_uuid: Optional[str],
    device_name: Optional[str] = None,
    device_type: Optional[str] = None,
    platform: Optional[str] = None,
) -> DeviceBindingResult:
    existing = await device_dao.get_by_device_id(device_id)
    already_linked = existing is not None and existing.telegram_id == telegram_id

    if not already_linked:
        linked_count = await device_dao.count_by_telegram_id(
            telegram_id,
            exclude_device_id=device_id,
        )
        if _is_device_limit_reached(linked_count, device_limit):
            return DeviceBindingResult(
                is_bound=False,
                device_limit=device_limit,
                message=f"Device limit reached. Maximum is {device_limit}.",
            )

    if existing:
        device_to_save = replace(
            existing,
            telegram_id=telegram_id,
            panel_user_uuid=panel_user_uuid,
            short_uuid=short_uuid,
            device_name=device_name if device_name is not None else existing.device_name,
            device_type=device_type if device_type is not None else existing.device_type,
            platform=platform if platform is not None else existing.platform,
        )
    else:
        device_to_save = LinkedDeviceDto(
            device_id=device_id,
            telegram_id=telegram_id,
            panel_user_uuid=panel_user_uuid,
            short_uuid=short_uuid,
            device_name=device_name,
            device_type=device_type,
            platform=platform,
        )

    device = await device_dao.upsert(device_to_save)
    return DeviceBindingResult(is_bound=True, device=device, device_limit=device_limit)
