from dataclasses import dataclass, replace
from typing import Literal

from src.application.common import Interactor
from src.application.common.dao import PaymentGatewayDao
from src.application.common.policy import Permission
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto
from src.application.dto.payment_gateway import RivaraGatewaySettingsDto
from src.core.enums import PaymentGatewayType


@dataclass(frozen=True)
class UpdateRivaraPaymentMethodDto:
    gateway_id: int
    method_id: str
    action: Literal["toggle", "rename", "reset_name"]
    name: str | None = None


class UpdateRivaraPaymentMethod(Interactor[UpdateRivaraPaymentMethodDto, None]):
    required_permission = Permission.REMNASHOP_GATEWAYS

    def __init__(self, uow: UnitOfWork, gateway_dao: PaymentGatewayDao) -> None:
        self.uow = uow
        self.gateway_dao = gateway_dao

    async def _execute(self, actor: UserDto, data: UpdateRivaraPaymentMethodDto) -> None:
        async with self.uow:
            gateway = await self.gateway_dao.get_by_id(data.gateway_id)
            if (
                gateway is None
                or gateway.type != PaymentGatewayType.RIVARAPAY
                or not isinstance(gateway.settings, RivaraGatewaySettingsDto)
            ):
                raise ValueError("Rivara Pay gateway not found")
            methods = gateway.settings.payment_methods
            method = next((entry for entry in methods if entry.id == data.method_id), None)
            if method is None:
                raise ValueError("Rivara Pay payment method not found")
            if data.action == "toggle":
                updated = replace(method, enabled=not method.enabled)
                if updated.enabled:
                    # General checkout and the separate method buttons are alternative modes.
                    methods = [
                        replace(entry, enabled=False)
                        if method.id == "ALL" or entry.id == "ALL"
                        else entry
                        for entry in methods
                    ]
            elif data.action == "rename":
                if not data.name or not data.name.strip():
                    raise ValueError("Payment method name must not be empty")
                updated = replace(method, display_name=data.name.strip())
            elif data.action == "reset_name":
                updated = replace(method, display_name=None)
            else:
                raise ValueError("Unsupported Rivara Pay payment method action")
            gateway.settings.methods = [
                updated if entry.id == method.id else entry for entry in methods
            ]
            await self.gateway_dao.update(gateway)
            await self.uow.commit()
