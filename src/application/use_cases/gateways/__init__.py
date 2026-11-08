from typing import Final

from src.application.common.interactor import Interactor

from .commands.configuration import (
    MovePaymentGatewayUp,
    ResetPaymentGatewaySettingsField,
    TogglePaymentGatewayActive,
    UpdatePaymentGatewaySettings,
)
from .commands.flippay_methods import RefreshFlippayPaymentMethods, UpdateFlippayPaymentMethod
from .commands.payment import (
    CreateDefaultPaymentGateway,
    CreatePayment,
    CreateTestPayment,
    ProcessPayment,
)
from .commands.recheck import RecheckPayment
from .commands.rivara_methods import UpdateRivaraPaymentMethod
from .queries.providers import GetPaymentGatewayInstance

GATEWAYS_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    GetPaymentGatewayInstance,
    MovePaymentGatewayUp,
    TogglePaymentGatewayActive,
    UpdatePaymentGatewaySettings,
    ResetPaymentGatewaySettingsField,
    CreateDefaultPaymentGateway,
    CreatePayment,
    CreateTestPayment,
    ProcessPayment,
    RecheckPayment,
    RefreshFlippayPaymentMethods,
    UpdateFlippayPaymentMethod,
    UpdateRivaraPaymentMethod,
)
