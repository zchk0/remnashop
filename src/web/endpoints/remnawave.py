import json
from typing import Any, cast

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, HTTPException, Request, Response, status
from loguru import logger
from remnapy.controllers import WebhookUtility
from remnapy.models.webhook import (
    NodeDto,
    TorrentBlockerReportDto,
    UserDto,
    UserHwidDeviceEventDto,
    WebhookPayloadDto,
)

from src.application.common import EventPublisher
from src.application.events import ErrorEvent
from src.application.services import RemnaWebhookService
from src.core.config import AppConfig
from src.core.constants import API_V1, REMNAWAVE_WEBHOOK_PATH
from src.core.utils.remnawave import extract_expiration_hours
from src.infrastructure.remnawave_v3.models import User as V3User
from src.infrastructure.remnawave_v3.webhook import V3DeviceEvent, V3TorrentReport, parse_v3_event

router = APIRouter(prefix=API_V1, include_in_schema=False)


def _validate_webhook(
    raw_body_text: str, headers: dict[str, str], config: AppConfig
) -> WebhookPayloadDto | None:
    if getattr(config.remnawave, "api_version", 2) == 3:
        if not WebhookUtility.validate_webhook_with_headers(
            body=raw_body_text,
            headers=headers,
            webhook_secret=config.remnawave.webhook_secret.get_secret_value(),
        ):
            raise ValueError("Invalid webhook signature")
        payload = None
    else:
        payload = WebhookUtility.parse_webhook(
            body=raw_body_text,
            headers=headers,
            webhook_secret=config.remnawave.webhook_secret.get_secret_value(),
            validate=True,
        )
    if payload is None and getattr(config.remnawave, "api_version", 2) == 2:
        raise ValueError("Invalid webhook signature")
    return payload


async def _dispatch_v3_webhook(
    raw_payload: dict[str, Any], remna_webhook_service: RemnaWebhookService
) -> None:
    event_name, data = parse_v3_event(raw_payload)
    if isinstance(data, V3User):
        await remna_webhook_service.handle_user_event(
            event_name, data, expiration_hours=extract_expiration_hours(raw_payload)
        )
    elif isinstance(data, V3DeviceEvent):
        await remna_webhook_service.handle_device_event(
            event_name, data.user, data.hwid_user_device
        )
    elif isinstance(data, NodeDto):
        await remna_webhook_service.handle_node_event(event_name, data)
    elif isinstance(data, V3TorrentReport):
        await remna_webhook_service.handle_torrent_blocker_event(data)
    else:
        logger.warning(f"Unhandled Remnawave event type '{event_name}'")


async def _process_remnawave_webhook(
    request: Request,
    config: AppConfig,
    remna_webhook_service: RemnaWebhookService,
    event_publisher: EventPublisher,
) -> Response:
    try:
        raw_body = await request.body()
        raw_body_text = raw_body.decode("utf-8")
        raw_payload = json.loads(raw_body_text)
        payload = _validate_webhook(raw_body_text, dict(request.headers), config)
    except Exception as e:
        logger.exception(f"Webhook validation failed with error '{e}'")
        raise HTTPException(status_code=401)

    try:
        if getattr(config.remnawave, "api_version", 2) == 3:
            await _dispatch_v3_webhook(raw_payload, remna_webhook_service)
            return Response(status_code=status.HTTP_200_OK)

        assert payload is not None
        if WebhookUtility.is_user_event(payload.event):
            user = cast(UserDto, WebhookUtility.get_typed_data(payload))
            await remna_webhook_service.handle_user_event(
                payload.event,
                user,
                expiration_hours=extract_expiration_hours(raw_payload),
            )

        elif WebhookUtility.is_user_hwid_devices_event(payload.event):
            event = cast(UserHwidDeviceEventDto, WebhookUtility.get_typed_data(payload))
            await remna_webhook_service.handle_device_event(
                payload.event,
                event.user,
                event.hwid_user_device,
            )

        elif WebhookUtility.is_node_event(payload.event):
            node = cast(NodeDto, WebhookUtility.get_typed_data(payload))
            await remna_webhook_service.handle_node_event(payload.event, node)

        elif WebhookUtility.is_torrent_blocker_event(payload.event):
            report = cast(TorrentBlockerReportDto, WebhookUtility.get_typed_data(payload))
            await remna_webhook_service.handle_torrent_blocker_event(report)

        else:
            logger.warning(f"Unhandled Remnawave event type '{payload.event}'")

    except Exception as e:
        logger.exception(f"Failed to process Remnawave webhook due to '{e}'")
        error_event = ErrorEvent(**config.build.data, exception=e)
        await event_publisher.publish(error_event)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    return Response(status_code=status.HTTP_200_OK)


@router.post(REMNAWAVE_WEBHOOK_PATH)
@inject
async def remnawave_webhook(
    request: Request,
    config: FromDishka[AppConfig],
    remna_webhook_service: FromDishka[RemnaWebhookService],
    event_publisher: FromDishka[EventPublisher],
) -> Response:
    return await _process_remnawave_webhook(
        request=request,
        config=config,
        remna_webhook_service=remna_webhook_service,
        event_publisher=event_publisher,
    )
