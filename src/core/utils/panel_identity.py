import hashlib
from typing import Any, TypeAlias
from uuid import UUID

PanelUserRef: TypeAlias = UUID | int


class PanelApiVersionMismatchError(ValueError):
    pass


def panel_user_ref(legacy_uuid: UUID | str | None, numeric_id: int | None) -> PanelUserRef:
    """Use a saved numeric ID when available; never invent a replacement UUID."""
    if numeric_id is not None:
        if type(numeric_id) is not int or numeric_id <= 0:
            raise ValueError("Invalid numeric panel user ID")
        return numeric_id
    if legacy_uuid is not None:
        return legacy_uuid if isinstance(legacy_uuid, UUID) else UUID(legacy_uuid)
    raise ValueError("Panel user has neither a numeric ID nor a legacy UUID")


def subscription_ref(subscription: Any) -> PanelUserRef:
    return panel_user_ref(subscription.user_remna_id, getattr(subscription, "panel_user_id", None))


def remote_user_ref(user: Any) -> PanelUserRef:
    # v2 responses have a UUID, so existing v2 operations need no extra lookup.
    if user.uuid is not None:
        return panel_user_ref(user.uuid, None)
    return panel_user_ref(None, user.id)


def device_user_ref(device: Any) -> PanelUserRef:
    return panel_user_ref(device.panel_user_uuid, getattr(device, "panel_user_id", None))


def anonymous_panel_username(device_id: str) -> str:
    return "app_" + hashlib.sha256(device_id.encode()).hexdigest()[:32]


def subscription_display_id(subscription: Any) -> str:
    numeric_id = getattr(subscription, "panel_user_id", None)
    legacy_uuid = getattr(subscription, "user_remna_id", getattr(subscription, "uuid", None))
    return (
        str(numeric_id if numeric_id is not None else legacy_uuid)
        if numeric_id is not None or legacy_uuid is not None
        else "—"
    )
