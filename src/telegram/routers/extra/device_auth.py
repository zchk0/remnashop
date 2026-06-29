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

from src.application.common import Remnawave, TranslatorRunner
from src.application.common.dao.device import AuthTokenDao, LinkedDeviceDao
from src.application.common.uow import UnitOfWork
from src.application.dto import PlanSnapshotDto, UserDto
from src.application.services.device_binding import bind_linked_device
from src.application.use_cases.subscription.commands.purchase import (
    ActivateTrialSubscription,
    ActivateTrialSubscriptionDto,
)
from src.application.use_cases.user.queries.plans import GetAvailableTrial
from src.core.enums import Deeplink
from src.core.utils.converters import gb_to_bytes
from src.core.utils.device_description import (
    append_device_id_to_description,
    extract_device_id_from_description,
)

router = Router(name=__name__)


def _is_auth_token(args: str) -> bool:
    """Return True if the deep-link payload looks like an auth token (not a known deep-link)."""
    known_prefixes = (
        Deeplink.BUY.with_underscore,
        Deeplink.REFERRAL.value,
        Deeplink.PLAN.value,
        Deeplink.INVITE.value,
        Deeplink.ADVERTISING.value,
        Deeplink.PROMOCODE.value,
    )
    return bool(args) and not any(args.startswith(p) for p in known_prefixes)


async def _update_panel_user_device_comment(
    remnawave: Remnawave,
    panel_user_uuid: UUID,
    panel_user_description: str | None,
    device_id: str,
) -> None:
    new_description = append_device_id_to_description(panel_user_description, device_id)
    if new_description == (panel_user_description or "").strip():
        return

    await remnawave.update_user_description(panel_user_uuid, new_description)
    logger.info(f"Saved device_id for panel user '{panel_user_uuid}'")


async def _transfer_anon_subscription_and_delete(
    anon_uuid: str,
    device_id: str,
    panel_user_uuid: UUID,
    panel_user_description: str | None,
    device_dao: LinkedDeviceDao,
    remnawave: Remnawave,
    uow: UnitOfWork,
) -> int:
    anon_user = None
    anon_traffic = 0

    try:
        anon_user = await remnawave.get_user_by_uuid(UUID(anon_uuid))
    except Exception as e:
        logger.warning(f"Failed to fetch anon user '{anon_uuid}': {e}")

    comment_device_id = (
        extract_device_id_from_description(anon_user.description if anon_user else None)
        or device_id
    )

    try:
        await _update_panel_user_device_comment(
            remnawave=remnawave,
            panel_user_uuid=panel_user_uuid,
            panel_user_description=panel_user_description,
            device_id=comment_device_id,
        )
    except Exception as e:
        logger.warning(f"Failed to save device_id for panel user '{panel_user_uuid}': {e}")

    try:
        if anon_user and anon_user.user_traffic:
            anon_traffic = int(anon_user.user_traffic.lifetime_used_traffic_bytes or 0)
            if anon_traffic > 0:
                await device_dao.add_anon_traffic(device_id, anon_traffic)
                await uow.commit()
                logger.info(f"Added {anon_traffic} anon bytes for device '{device_id}'")
    except Exception as e:
        logger.warning(f"Failed to save anon traffic for device '{device_id}': {e}")

    try:
        await remnawave.delete_user(UUID(anon_uuid))
        logger.info(f"Deleted anon panel user '{anon_uuid}'")
    except Exception as e:
        logger.warning(f"Failed to clean up anon user '{anon_uuid}': {e}")

    return anon_traffic


async def _apply_anon_traffic_to_trial_limit(
    remnawave: Remnawave,
    panel_user_uuid: UUID,
    trial_traffic_limit_gb: int,
    anon_traffic_bytes: int,
) -> None:
    trial_traffic_limit_bytes = gb_to_bytes(trial_traffic_limit_gb)
    if trial_traffic_limit_bytes <= 0 or anon_traffic_bytes <= 0:
        return

    remaining_traffic_limit_bytes = max(trial_traffic_limit_bytes - anon_traffic_bytes, 1)
    await remnawave.update_user_traffic_limit(panel_user_uuid, remaining_traffic_limit_bytes)
    logger.info(
        f"Applied anon traffic '{anon_traffic_bytes}' bytes to trial user "
        f"'{panel_user_uuid}', remaining limit '{remaining_traffic_limit_bytes}' bytes"
    )


@inject
@router.message(
    CommandStart(deep_link=True, ignore_case=True),
    ~F.text.contains(Deeplink.PLAN),
    ~F.text.contains(Deeplink.INVITE),
    ~F.text.contains(Deeplink.REFERRAL),
    ~F.text.contains(Deeplink.ADVERTISING),
    ~F.text.contains(Deeplink.PROMOCODE),
    ~F.text.contains(Deeplink.BUY.with_underscore),
)
async def on_device_auth(  # noqa: C901
    message: Message,
    command: CommandObject,
    user: UserDto,
    auth_dao: FromDishka[AuthTokenDao],
    device_dao: FromDishka[LinkedDeviceDao],
    get_available_trial: FromDishka[GetAvailableTrial],
    activate_trial_subscription: FromDishka[ActivateTrialSubscription],
    remnawave: FromDishka[Remnawave],
    uow: FromDishka[UnitOfWork],
    i18n: FromDishka[TranslatorRunner],
) -> None:
    args = command.args or ""
    if not _is_auth_token(args):
        return

    auth_token = args
    telegram_id = message.from_user.id

    token_record = await auth_dao.get_by_token(auth_token)
    if not token_record:
        await message.answer(i18n.get("msg-device-auth-token-not-found"))
        return

    if token_record.status == "completed":
        await message.answer(i18n.get("msg-device-auth-already-authorized"))
        return

    anon_uuid = token_record.panel_user_uuid

    existing_users = await remnawave.get_user_by_telegram_id(telegram_id)
    existing_user = existing_users[0] if existing_users else None

    panel_user = None
    created_trial = False
    trial: PlanSnapshotDto | None = None

    if existing_user:
        panel_user = existing_user
    else:
        if not user.is_trial_available:
            await message.answer(i18n.get("msg-device-auth-trial-not-available"))
            logger.warning(f"{user.log} ToBeVPN auth failed: trial is not available")
            return

        trial_plan = await get_available_trial.system(user)
        if not trial_plan:
            await message.answer(i18n.get("msg-device-auth-trial-plan-not-available"))
            logger.warning(f"{user.log} ToBeVPN auth failed: no available trial plan")
            return

        trial = PlanSnapshotDto.from_plan(trial_plan, trial_plan.durations[0].days)

        try:
            await activate_trial_subscription.system(
                ActivateTrialSubscriptionDto(user=user, plan=trial)
            )
            created_trial = True
        except Exception as e:
            await message.answer(i18n.get("msg-device-auth-trial-create-failed"))
            logger.warning(f"{user.log} ToBeVPN trial activation failed: {e}")
            return

        existing_users = await remnawave.get_user_by_telegram_id(telegram_id)
        panel_user = existing_users[0] if existing_users else None

    if not panel_user:
        await message.answer(i18n.get("msg-device-auth-linking-failed"))
        logger.warning(f"Failed auth for telegram '{telegram_id}': panel user not resolved")
        return

    short_uuid = str(panel_user.short_uuid) if panel_user.short_uuid else None
    panel_uuid = str(panel_user.uuid) if panel_user.uuid else None
    if not await auth_dao.complete(auth_token, telegram_id, short_uuid):
        await uow.rollback()
        await message.answer(i18n.get("msg-device-auth-already-authorized"))
        logger.warning(f"{user.log} ToBeVPN auth failed: auth token already used")
        return

    binding = await bind_linked_device(
        device_dao,
        device_id=token_record.device_id,
        telegram_id=telegram_id,
        device_limit=panel_user.hwid_device_limit or 0,
        panel_user_uuid=panel_uuid,
        short_uuid=short_uuid,
    )
    if not binding.is_bound:
        await uow.rollback()
        await message.answer(
            i18n.get(
                "msg-device-auth-device-limit-reached",
                device_limit=binding.device_limit,
            )
        )
        logger.warning(
            f"{user.log} ToBeVPN auth failed: device limit '{binding.device_limit}' reached"
        )
        return

    anon_traffic = 0
    if anon_uuid:
        if str(anon_uuid) == str(panel_user.uuid):
            try:
                await _update_panel_user_device_comment(
                    remnawave=remnawave,
                    panel_user_uuid=panel_user.uuid,
                    panel_user_description=panel_user.description,
                    device_id=token_record.device_id,
                )
            except Exception as e:
                logger.warning(f"Failed to save device_id for panel user '{panel_user.uuid}': {e}")
        else:
            anon_traffic = await _transfer_anon_subscription_and_delete(
                anon_uuid=anon_uuid,
                device_id=token_record.device_id,
                panel_user_uuid=panel_user.uuid,
                panel_user_description=panel_user.description,
                device_dao=device_dao,
                remnawave=remnawave,
                uow=uow,
            )

    if created_trial and trial and anon_traffic > 0:
        try:
            await _apply_anon_traffic_to_trial_limit(
                remnawave=remnawave,
                panel_user_uuid=panel_user.uuid,
                trial_traffic_limit_gb=trial.traffic_limit,
                anon_traffic_bytes=anon_traffic,
            )
        except Exception as e:
            logger.warning(
                f"Failed to apply anon traffic '{anon_traffic}' bytes to "
                f"trial user '{panel_user.uuid}': {e}"
            )

    await uow.commit()

    await message.answer(i18n.get("msg-device-auth-success"))
    logger.info(f"User '{telegram_id}' authorized, panel shortUuid={short_uuid}")
