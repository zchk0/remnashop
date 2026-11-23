import asyncio
import time
from datetime import timedelta
from random import uniform

from dishka.integrations.taskiq import FromDishka, inject
from loguru import logger

from src.application.common.uow import UnitOfWork
from src.core.config import AppConfig
from src.infrastructure.database.dao.tobevpn_notification import ToBeVpnNotificationDao
from src.infrastructure.services.fcm import FcmClient
from src.infrastructure.taskiq.broker import broker


@broker.task(schedule=[{"cron": "* * * * *"}])
@inject(patch_module=True)
async def send_tobevpn_pushes(
    config: FromDishka[AppConfig],
    notifications: FromDishka[ToBeVpnNotificationDao],
    uow: FromDishka[UnitOfWork],
    fcm: FromDishka[FcmClient],
) -> None:
    if not config.tobevpn.is_enabled or fcm.account is None:
        return

    deadline = time.monotonic() + 35
    sent = failed = 0
    while time.monotonic() < deadline:
        batch, discard, lease_until = await notifications.claim_push(limit=16)
        await uow.commit()
        if not batch and not discard:
            break
        results = await asyncio.gather(*(fcm.send(delivery) for delivery in batch))
        for delivery, result in zip(batch, results, strict=True):
            if result.retry_after is not None and delivery.attempts < 5:
                seconds = max(result.retry_after, 60 * 2 ** (delivery.attempts - 1))
                await notifications.retry_push(
                    delivery.id,
                    timedelta(seconds=min(seconds, 86_400) + uniform(0, 15)),
                    lease_until,
                )
                continue
            if result.unregistered:
                await notifications.remove_invalid_push_token(delivery)
            discard.append(delivery.id)
            sent += int(result.delivered)
            failed += int(not result.delivered)
        await notifications.finish_push(discard, lease_until)
        await uow.commit()

    if sent or failed:
        logger.info(f"ToBeVPN pushes: accepted by Firebase={sent}, failed={failed}")


@broker.task(schedule=[{"cron": "26 3 * * *"}])
@inject(patch_module=True)
async def cleanup_tobevpn_notifications(
    notifications: FromDishka[ToBeVpnNotificationDao],
    uow: FromDishka[UnitOfWork],
) -> None:
    await notifications.delete_expired()
    await uow.commit()
