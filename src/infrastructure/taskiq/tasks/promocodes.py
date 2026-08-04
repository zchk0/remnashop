from dishka.integrations.taskiq import FromDishka, inject
from loguru import logger

from src.application.common.dao import PromocodeDao, UserDao
from src.application.use_cases.promocode.commands.activate import (
    ActivatePromocode,
    ActivatePromocodeDto,
)
from src.infrastructure.taskiq.broker import broker


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
        promo = await promocode_dao.get_by_id(activation.promocode_id)
        if user is None or promo is None:
            logger.error(
                f"Cannot resume promocode activation '{activation.request_id}': "
                "user or promocode not found"
            )
            continue

        try:
            await activate_promocode(
                user,
                ActivatePromocodeDto(
                    code=promo.code,
                    user=user,
                    request_id=activation.request_id,
                ),
            )
        except Exception:
            logger.exception(
                f"Failed to resume promocode activation '{activation.request_id}'"
            )
