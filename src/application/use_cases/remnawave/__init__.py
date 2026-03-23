from typing import Final

from src.application.common import Interactor

from .commands.management import (
    DeleteUserAllDevices,
    DeleteUserDevice,
    ReissueSubscription,
    ResetUserTraffic,
)
from .commands.synchronization import SyncRemnaUser

REMNAWAVE_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    SyncRemnaUser,
    DeleteUserDevice,
    DeleteUserAllDevices,
    ResetUserTraffic,
    ReissueSubscription,
)
