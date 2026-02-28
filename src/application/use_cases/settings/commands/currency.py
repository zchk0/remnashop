from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import SettingsDao
from src.application.common.policy import Permission
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto
from src.core.enums import Currency


class UpdateDefaultCurrency(Interactor[Currency, None]):
    required_permission = Permission.SETTINGS_CURRENCY

    def __init__(self, uow: UnitOfWork, settings_dao: SettingsDao) -> None:
        self.uow = uow
        self.settings_dao = settings_dao

    async def _execute(self, actor: UserDto, currency: Currency) -> None:
        async with self.uow:
            settings = await self.settings_dao.get()
            old_currency = settings.default_currency

            if old_currency == currency:
                logger.debug(f"Default currency is already set to '{currency}'")
                return

            settings.default_currency = currency
            await self.settings_dao.update(settings)
            await self.uow.commit()

        logger.info(f"{actor.log} Updated default currency from '{old_currency}' to '{currency}'")
