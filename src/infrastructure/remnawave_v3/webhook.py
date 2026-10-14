from typing import Any

from pydantic import AwareDatetime, BaseModel, ValidationError
from remnapy.models.node_plugins import TorrentBlockerReportPayloadDto
from remnapy.models.webhook import NodeDto

from .client import PanelV3ResponseError
from .models import HwidDevice, ResponseModel, User


class V3DeviceEvent(ResponseModel):
    user: User
    hwid_user_device: HwidDevice


class V3TorrentReport(ResponseModel):
    node: NodeDto
    user: User
    report: TorrentBlockerReportPayloadDto


class V3Webhook(BaseModel):
    event: str
    timestamp: AwareDatetime
    data: dict[str, Any]


def _parse_v3_event(
    payload: dict[str, Any],
) -> tuple[str, User | V3DeviceEvent | NodeDto | V3TorrentReport | None]:
    envelope = V3Webhook.model_validate(payload)
    event = envelope.event
    if event.startswith("user."):
        return event, User.model_validate(envelope.data)
    if event.startswith("user_hwid_devices."):
        return event, V3DeviceEvent.model_validate(envelope.data)
    if event.startswith("node."):
        return event, NodeDto.model_validate(envelope.data)
    if event.startswith("torrent_blocker."):
        return event, V3TorrentReport.model_validate(envelope.data)
    return event, None


def parse_v3_event(
    payload: dict[str, Any],
) -> tuple[str, User | V3DeviceEvent | NodeDto | V3TorrentReport | None]:
    try:
        return _parse_v3_event(payload)
    except ValidationError:
        raise PanelV3ResponseError("Invalid v3 webhook schema") from None
