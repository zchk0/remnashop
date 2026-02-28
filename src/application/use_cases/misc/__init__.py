from typing_extensions import Final

from src.application.common import Interactor

from .commands.maintenance import CancelOldTransactions, ClearOldBroadcasts
from .commands.menu_editor import (
    ConfirmMenuButtonChanges,
    UpdateMenuButtonPayload,
    UpdateMenuButtonText,
)
from .commands.navigation import RedirectMenu
from .queries.logs import GetLogs
from .queries.menu import GetMenuData

MISC_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    GetLogs,
    UpdateMenuButtonText,
    UpdateMenuButtonPayload,
    ConfirmMenuButtonChanges,
    GetMenuData,
    RedirectMenu,
    CancelOldTransactions,
    ClearOldBroadcasts,
)
