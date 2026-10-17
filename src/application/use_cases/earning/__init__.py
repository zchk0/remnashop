from .channels import GetEarningChannels
from .manage import ManageChannelTask, ResetChannelTaskCompletions, UpdateEarningSettings
from .rewards import ClaimChannelReward, GetEarningTasks, ResolveEarningClaim

EARNING_USE_CASES = (
    GetEarningChannels,
    ManageChannelTask,
    ResetChannelTaskCompletions,
    UpdateEarningSettings,
    ClaimChannelReward,
    GetEarningTasks,
    ResolveEarningClaim,
)
