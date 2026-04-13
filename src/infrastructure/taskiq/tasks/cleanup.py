from dishka.integrations.taskiq import FromDishka, inject
from loguru import logger

from src.application.common.dao.device import AuthTokenDao, TvPairingDao
from src.application.common.uow import UnitOfWork
from src.core.constants import TV_PAIRING_TTL_SECONDS
from src.infrastructure.taskiq.broker import broker


@broker.task(schedule=[{"cron": "0 * * * *"}])
@inject(patch_module=True)
async def cleanup_expired_tokens_and_codes(
    auth_dao: FromDishka[AuthTokenDao],
    pairing_dao: FromDishka[TvPairingDao],
    uow: FromDishka[UnitOfWork],
) -> None:
    """Hourly cleanup of expired auth tokens and TV pairing codes."""
    tokens_cleaned = await auth_dao.cleanup_expired(max_age_seconds=86400)
    codes_cleaned = await pairing_dao.cleanup_expired(
        ttl_seconds=TV_PAIRING_TTL_SECONDS, completed_grace_seconds=600
    )
    await uow.commit()

    if tokens_cleaned or codes_cleaned:
        logger.info(
            f"Cleanup: removed {tokens_cleaned} expired auth tokens "
            f"and {codes_cleaned} expired TV pairing codes"
        )
