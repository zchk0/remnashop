"""
Deep-link authentication handler for ToBeVPN mobile/TV apps.

Handles /start <auth_token> deep links: when a user clicks the auth link in the
mobile app, this handler links their Telegram identity to their device and
Remnawave panel account.
"""

from uuid import UUID

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.application.common import Remnawave
from src.application.common.dao.device import AuthTokenDao, LinkedDeviceDao
from src.application.common.uow import UnitOfWork
from src.application.dto import PlanSnapshotDto, UserDto
from src.application.dto.device import LinkedDeviceDto
from src.application.use_cases.subscription.commands.purchase import (
    ActivateTrialSubscription,
    ActivateTrialSubscriptionDto,
)
from src.application.use_cases.user.queries.plans import GetAvailableTrial
from src.core.enums import Deeplink

router = Router(name=__name__)


def _is_auth_token(args: str) -> bool:
    """Return True if the deep-link payload looks like an auth token (not a known deep-link)."""
    known_prefixes = (
        Deeplink.BUY.with_underscore,
        Deeplink.REFERRAL.value,
        Deeplink.PLAN.value,
        Deeplink.INVITE.value,
    )
    return bool(args) and not any(args.startswith(p) for p in known_prefixes)


async def _save_anon_traffic_and_delete(
    anon_uuid: str,
    device_id: str,
    device_dao: LinkedDeviceDao,
    remnawave: Remnawave,
    uow: UnitOfWork,
) -> None:
    try:
        anon_user = await remnawave.get_user_by_uuid(UUID(anon_uuid))
        if anon_user and anon_user.user_traffic:
            anon_traffic = int(anon_user.user_traffic.lifetime_used_traffic_bytes or 0)
            if anon_traffic > 0:
                await device_dao.add_anon_traffic(device_id, anon_traffic)
                await uow.commit()
                logger.info(f"Saved {anon_traffic} anon bytes for device '{device_id}'")

        await remnawave.delete_user(UUID(anon_uuid))
        logger.info(f"Deleted anon panel user '{anon_uuid}'")
    except Exception as e:
        logger.warning(f"Failed to clean up anon user '{anon_uuid}': {e}")


@inject
@router.message(
    CommandStart(deep_link=True, ignore_case=True),
    ~F.text.contains(Deeplink.PLAN),
    ~F.text.contains(Deeplink.INVITE),
    ~F.text.contains(Deeplink.REFERRAL),
    ~F.text.contains(Deeplink.BUY.with_underscore),
)
async def on_device_auth(
    message: Message,
    command: CommandObject,
    user: UserDto,
    auth_dao: FromDishka[AuthTokenDao],
    device_dao: FromDishka[LinkedDeviceDao],
    get_available_trial: FromDishka[GetAvailableTrial],
    activate_trial_subscription: FromDishka[ActivateTrialSubscription],
    remnawave: FromDishka[Remnawave],
    uow: FromDishka[UnitOfWork],
) -> None:
    args = command.args or ""
    if not _is_auth_token(args):
        return

    auth_token = args
    telegram_id = message.from_user.id

    token_record = await auth_dao.get_by_token(auth_token)
    if not token_record:
        await message.answer("Auth token not found or expired.")
        return

    if token_record.status == "completed":
        await message.answer("Already authorized!")
        return

    anon_uuid = token_record.panel_user_uuid

    existing_users = await remnawave.get_user_by_telegram_id(telegram_id)
    existing_user = existing_users[0] if existing_users else None

    panel_user = None

    if existing_user:
        panel_user = existing_user
        if anon_uuid and str(anon_uuid) != str(existing_user.uuid):
            await _save_anon_traffic_and_delete(
                anon_uuid=anon_uuid,
                device_id=token_record.device_id,
                device_dao=device_dao,
                remnawave=remnawave,
                uow=uow,
            )
    else:
        if not user.is_trial_available:
            await message.answer("Trial is not available for this Telegram account.")
            logger.warning(f"{user.log} ToBeVPN auth failed: trial is not available")
            return

        trial_plan = await get_available_trial.system(user)
        if not trial_plan:
            await message.answer("Trial plan is not available.")
            logger.warning(f"{user.log} ToBeVPN auth failed: no available trial plan")
            return

        trial = PlanSnapshotDto.from_plan(trial_plan, trial_plan.durations[0].days)

        try:
            await activate_trial_subscription.system(
                ActivateTrialSubscriptionDto(user=user, plan=trial)
            )
        except Exception as e:
            await message.answer("Could not create trial subscription. Please try again later.")
            logger.warning(f"{user.log} ToBeVPN trial activation failed: {e}")
            return

        existing_users = await remnawave.get_user_by_telegram_id(telegram_id)
        panel_user = existing_users[0] if existing_users else None

        if panel_user and anon_uuid and str(anon_uuid) != str(panel_user.uuid):
            await _save_anon_traffic_and_delete(
                anon_uuid=anon_uuid,
                device_id=token_record.device_id,
                device_dao=device_dao,
                remnawave=remnawave,
                uow=uow,
            )

    if not panel_user:
        await message.answer(
            "Could not complete account linking.\nPlease try again in a few seconds."
        )
        logger.warning(f"Failed auth for telegram '{telegram_id}': panel user not resolved")
        return

    short_uuid = str(panel_user.short_uuid) if panel_user.short_uuid else None
    panel_uuid = str(panel_user.uuid) if panel_user.uuid else None

    await auth_dao.complete(auth_token, telegram_id, short_uuid)

    await device_dao.upsert(
        LinkedDeviceDto(
            device_id=token_record.device_id,
            telegram_id=telegram_id,
            panel_user_uuid=panel_uuid,
            short_uuid=short_uuid,
        )
    )
    await uow.commit()

    await message.answer("Authorization successful!\n\nReturn to the ToBeVPN app.")
    logger.info(f"User '{telegram_id}' authorized, panel shortUuid={short_uuid}")
