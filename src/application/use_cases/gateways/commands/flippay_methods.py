from dataclasses import dataclass, replace
from typing import Literal

from src.application.common import Interactor
from src.application.common.dao import PaymentGatewayDao
from src.application.common.policy import Permission
from src.application.common.uow import UnitOfWork
from src.application.dto import PaymentGatewayDto, UserDto
from src.application.dto.payment_gateway import FlippayGatewaySettingsDto
from src.core.enums import PaymentGatewayType
from src.infrastructure.payment_gateways import FlippayGateway, PaymentGatewayFactory


def _settings(gateway: PaymentGatewayDto | None) -> FlippayGatewaySettingsDto:
    if (
        gateway is None
        or gateway.type != PaymentGatewayType.FLIPPAY
        or not isinstance(gateway.settings, FlippayGatewaySettingsDto)
    ):
        raise ValueError("FlipPay gateway not found")
    return gateway.settings


class RefreshFlippayPaymentMethods(Interactor[int, int]):
    required_permission = Permission.REMNASHOP_GATEWAYS

    def __init__(
        self,
        uow: UnitOfWork,
        gateway_dao: PaymentGatewayDao,
        gateway_factory: PaymentGatewayFactory,
    ) -> None:
        self.uow = uow
        self.gateway_dao = gateway_dao
        self.gateway_factory = gateway_factory

    async def _execute(self, actor: UserDto, gateway_id: int) -> int:
        async with self.uow:
            gateway = await self.gateway_dao.get_by_id(gateway_id)
            settings = _settings(gateway)
            assert gateway is not None
            instance = self.gateway_factory(gateway)
            if not isinstance(instance, FlippayGateway):
                raise TypeError("Expected FlipPay gateway")
            available = await instance.get_payment_methods()
            previous = settings.payment_methods
            by_code = {method.code: method for method in previous}
            merged = []
            for method in available:
                old = by_code.get(method.code)
                if old is None and settings.methods is None:
                    # An older installation may have used a custom numeric method ID.
                    old = next(
                        (
                            entry
                            for entry in previous
                            if entry.id == method.id and entry.code == f"method_{entry.id}"
                        ),
                        None,
                    )
                if old is not None:
                    method = replace(method, enabled=old.enabled, display_name=old.display_name)
                merged.append(method)
            live_codes = {method.code for method in available}
            live_ids = {method.id for method in available}
            merged.extend(
                replace(method, available=False)
                for method in previous
                if method.code not in live_codes and method.id not in live_ids
            )
            settings.methods = merged
            await self.gateway_dao.update(gateway)
            await self.uow.commit()
        return len(available)


@dataclass(frozen=True)
class UpdateFlippayPaymentMethodDto:
    gateway_id: int
    method_id: int
    action: Literal["toggle", "rename", "reset_name"]
    name: str | None = None


class UpdateFlippayPaymentMethod(Interactor[UpdateFlippayPaymentMethodDto, None]):
    required_permission = Permission.REMNASHOP_GATEWAYS

    def __init__(self, uow: UnitOfWork, gateway_dao: PaymentGatewayDao) -> None:
        self.uow = uow
        self.gateway_dao = gateway_dao

    async def _execute(self, actor: UserDto, data: UpdateFlippayPaymentMethodDto) -> None:
        async with self.uow:
            gateway = await self.gateway_dao.get_by_id(data.gateway_id)
            settings = _settings(gateway)
            method = next(
                (entry for entry in settings.payment_methods if entry.id == data.method_id), None
            )
            if method is None:
                raise ValueError("FlipPay payment method not found")
            if data.action == "toggle":
                if not method.available and not method.enabled:
                    raise ValueError("FlipPay method is unavailable for this merchant")
                updated = replace(method, enabled=not method.enabled)
            elif data.action == "rename":
                if not data.name or not data.name.strip():
                    raise ValueError("Payment method name must not be empty")
                updated = replace(method, display_name=data.name.strip())
            elif data.action == "reset_name":
                updated = replace(method, display_name=None)
            else:
                raise ValueError("Unsupported FlipPay payment method action")
            settings.methods = [
                updated if entry.id == method.id else entry for entry in settings.payment_methods
            ]
            assert gateway is not None
            await self.gateway_dao.update(gateway)
            await self.uow.commit()
