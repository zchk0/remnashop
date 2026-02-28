from typing import Final

from src.application.common import Interactor

from .commands.processing import ProcessImportFile
from .queries.filters import SplitExportedUsers
from .queries.xui import ExportUsersFromXui

IMPORTER_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    ExportUsersFromXui,
    SplitExportedUsers,
    ProcessImportFile,
)
