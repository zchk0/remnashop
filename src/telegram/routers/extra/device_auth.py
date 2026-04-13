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
from remnapy import RemnawaveSDK
from remnapy.models import UpdateUserRequestDto

from src.application.common import Remnawave
from src.application.common.dao.device import AuthTokenDao, LinkedDeviceDao
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto
from src.application.dto.device import LinkedDeviceDto
from src.core.enums import Deeplink

router = Router(name=__name__)


def _is_auth_token(args: str) -> bool:
    """Return True if the deep-link payload looks like an auth token (not a known deep-link)."""
    known_prefixes = (
        "buy_",
        Deeplink.REFERRAL.value,
        Deeplink.PLAN.value,
        Deeplink.INVITE.value,
    )
    return bool(args) and not any(args.startswith(p) for p in known_prefixes)


@inject
@router.message(
    CommandStart(deep_link=True, ignore_case=True),
    ~F.text.contains(Deeplink.PLAN),
    ~F.text.contains(Deeplink.INVITE),
    ~F.text.contains(Deeplink.REFERRAL),
)
async def on_device_auth(
    message: Message,
    command: CommandObject,
    user: UserDto,
    auth_dao: FromDishka[AuthTokenDao],
    device_dao: FromDishka[LinkedDeviceDao],
    remnawave: FromDishka[Remnawave],
    remnawave_sdk: FromDishka[RemnawaveSDK],
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

    # Try to find existing panel user by telegram_id
    existing_users = await remnawave.get_user_by_telegram_id(telegram_id)
    existing_user = existing_users[0] if existing_users else None

    panel_user = None

    if existing_user:
        # Returning user (reinstall) — use existing account, delete anonymous
        panel_user = existing_user
        if anon_uuid and str(anon_uuid) != str(existing_user.uuid):
            try:
                anon_user = await remnawave.get_user_by_uuid(UUID(anon_uuid))
                if anon_user and anon_user.user_traffic:
                    anon_traffic = anon_user.user_traffic.lifetime_used_traffic_bytes or 0
                    if anon_traffic > 0:
                        await device_dao.add_anon_traffic(token_record.device_id, anon_traffic)
                        logger.info(
                            f"Saved {anon_traffic} anon bytes for device '{token_record.device_id}'"
                        )
                await remnawave.delete_user(UUID(anon_uuid))
                logger.info(f"Deleted anon panel user '{anon_uuid}'")
            except Exception as e:
                logger.warning(f"Failed to clean up anon user '{anon_uuid}': {e}")
    elif anon_uuid:
        # First auth — link anonymous user to telegram via SDK directly
        try:
            linked = await remnawave_sdk.users.update_user(
                UpdateUserRequestDto(uuid=UUID(anon_uuid), telegram_id=telegram_id)
            )
            if linked:
                panel_user = linked
                logger.info(f"Linked anon user '{anon_uuid}' to telegram '{telegram_id}'")
        except Exception:
            pass

        if not panel_user:
            existing_users = await remnawave.get_user_by_telegram_id(telegram_id)
            panel_user = existing_users[0] if existing_users else None

    if not panel_user:
        await message.answer(
            "Could not complete account linking.\nPlease try again in a few seconds."
        )
        logger.warning(f"Failed auth for telegram '{telegram_id}': panel user not resolved")
        return

    short_uuid = str(panel_user.short_uuid) if panel_user.short_uuid else None
    panel_uuid = str(panel_user.uuid) if panel_user.uuid else None

    # Complete auth token
    await auth_dao.complete(auth_token, telegram_id, short_uuid)

    # Link the device
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
