from dishka.integrations.taskiq import FromDishka, inject
from loguru import logger

from src.application.common.dao.device import AuthTokenDao, DeviceSessionDao, TvPairingDao
from src.application.common.uow import UnitOfWork
from src.core.config import AppConfig
from src.core.constants import TV_PAIRING_TTL_SECONDS
from src.infrastructure.taskiq.broker import broker


@broker.task(schedule=[{"cron": "0 * * * *"}])
@inject(patch_module=True)
async def cleanup_expired_tokens_and_codes(
    config: FromDishka[AppConfig],
    auth_dao: FromDishka[AuthTokenDao],
    session_dao: FromDishka[DeviceSessionDao],
    pairing_dao: FromDishka[TvPairingDao],
    uow: FromDishka[UnitOfWork],
) -> None:
    """Hourly cleanup of expired auth tokens, device sessions and TV pairing codes."""
    tokens_cleaned = await auth_dao.cleanup_expired(
        max_age_seconds=config.tobevpn.auth_request_ttl_seconds
    )
    sessions_cleaned = await session_dao.cleanup_expired()
    codes_cleaned = await pairing_dao.cleanup_expired(
        ttl_seconds=TV_PAIRING_TTL_SECONDS, completed_grace_seconds=600
    )
    await uow.commit()

    if tokens_cleaned or sessions_cleaned or codes_cleaned:
        logger.info(
            f"Cleanup: removed {tokens_cleaned} expired auth tokens "
            f"{sessions_cleaned} expired device sessions and "
            f"{codes_cleaned} expired TV pairing codes"
        )
