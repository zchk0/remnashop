from .manage import ManageChannelTask, UpdateEarningSettings
from .rewards import ClaimChannelReward, GetEarningTasks, ResolveEarningClaim

EARNING_USE_CASES = (
    ManageChannelTask,
    UpdateEarningSettings,
    ClaimChannelReward,
    GetEarningTasks,
    ResolveEarningClaim,
)
