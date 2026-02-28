from typing import Final

from src.application.common import Interactor

from .commands.blocking import SetBotBlockedStatus, ToggleUserBlockedStatus, UnblockAllUsers
from .commands.messaging import SendMessageToUser
from .commands.profile_edit import ChangeUserPoints, SetUserPersonalDiscount
from .commands.registration import GetOrCreateUser
from .commands.roles import GetAdmins, RevokeRole, SetUserRole
from .queries.plans import GetAvailablePlans, GetAvailableTrial
from .queries.profile import GetUserDevices, GetUserProfile, GetUserProfileSubscription
from .queries.search import SearchUsers

USER_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    GetAdmins,
    GetOrCreateUser,
    SetBotBlockedStatus,
    ToggleUserBlockedStatus,
    RevokeRole,
    SetUserRole,
    SearchUsers,
    UnblockAllUsers,
    GetUserProfile,
    GetUserProfileSubscription,
    GetUserDevices,
    GetAvailablePlans,
    SetUserPersonalDiscount,
    ChangeUserPoints,
    SendMessageToUser,
    GetAvailableTrial,
)
