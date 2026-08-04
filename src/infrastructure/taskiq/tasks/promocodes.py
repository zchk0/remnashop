from datetime import timedelta

from dishka.integrations.taskiq import FromDishka, inject
from loguru import logger

from src.application.common.dao import PromocodeDao, UserDao
from src.application.common.uow import UnitOfWork
from src.application.events.system import PromocodeActivatedEvent
from src.application.use_cases.promocode.commands.activate import (
    PROMOCODE_ACTIVATION_MAX_ATTEMPTS,
    ActivatePromocode,
    ActivatePromocodeDto,
    get_promocode_retry_delay,
)
from src.core.utils.time import datetime_now
from src.infrastructure.services.notification import NotificationService
from src.infrastructure.taskiq.broker import broker

PROMOCODE_EVENT_LEASE = timedelta(minutes=5)


@broker.task(schedule=[{"cron": "* * * * *"}], retry_on_error=False)
@inject(patch_module=True)
async def retry_pending_promocode_activations(
    promocode_dao: FromDishka[PromocodeDao],
    user_dao: FromDishka[UserDao],
    activate_promocode: FromDishka[ActivatePromocode],
) -> None:
    pending_activations = await promocode_dao.get_pending_activations(limit=100)

    for activation in pending_activations:
        if activation.request_id is None:
            continue

        user = await user_dao.get_by_id(activation.user_id)
        if user is None:
            logger.error(
                f"Cannot resume promocode activation '{activation.request_id}': "
                "user not found"
            )
            continue

        try:
            await activate_promocode(
                user,
                ActivatePromocodeDto(
                    code=activation.code_snapshot,
                    user=user,
                    request_id=activation.request_id,
                ),
            )
        except Exception:
            logger.exception(
                f"Failed to resume promocode activation '{activation.request_id}'"
            )


@broker.task(schedule=[{"cron": "* * * * *"}], retry_on_error=False)
@inject(patch_module=True)
async def dispatch_pending_promocode_activation_events(
    promocode_dao: FromDishka[PromocodeDao],
    user_dao: FromDishka[UserDao],
    uow: FromDishka[UnitOfWork],
    notification_service: FromDishka[NotificationService],
) -> None:
    async with uow:
        activations = await promocode_dao.claim_pending_activation_events(
            lease_until=datetime_now() + PROMOCODE_EVENT_LEASE,
            limit=100,
        )
        await uow.commit()

    for activation in activations:
        if activation.id is None:
            continue

        try:
            user = await user_dao.get_by_id(activation.user_id)
            if user is None:
                raise RuntimeError(f"User '{activation.user_id}' not found")

            event = PromocodeActivatedEvent(
                user_id=user.id,
                telegram_id=user.telegram_id,
                username=user.username,
                name=user.name,
                promocode_code=activation.code_snapshot,
                reward_type=activation.reward_type_snapshot.value,
                reward=activation.reward_snapshot,
                plan_name=(str(activation.plan_snapshot.get("name")), {})
                if activation.plan_snapshot and activation.plan_snapshot.get("name")
                else "",
            )
            await notification_service.deliver_system_event(event)
        except Exception as error:
            attempt_count = activation.event_attempt_count + 1
            next_retry_at = (
                None
                if attempt_count >= PROMOCODE_ACTIVATION_MAX_ATTEMPTS
                else datetime_now() + get_promocode_retry_delay(attempt_count)
            )
            async with uow:
                await promocode_dao.record_activation_event_failure(
                    activation_id=activation.id,
                    error=str(error),
                    attempt_count=attempt_count,
                    next_retry_at=next_retry_at,
                )
                await uow.commit()
            logger.exception(
                f"Failed to deliver promocode activation event '{activation.request_id}' "
                f"on attempt '{attempt_count}'"
            )
            continue

        async with uow:
            await promocode_dao.mark_activation_event_sent(
                activation_id=activation.id,
                sent_at=datetime_now(),
            )
            await uow.commit()
        logger.info(f"Delivered promocode activation event '{activation.request_id}'")
