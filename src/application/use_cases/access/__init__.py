from typing import Final

from src.application.common import Interactor

from .commands.validation import AcceptRules
from .queries.availability import CheckAccess
from .queries.requirements import CheckChannelSubscription, CheckRules

ACCESS_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    CheckAccess,
    AcceptRules,
    CheckRules,
    CheckChannelSubscription,
)
