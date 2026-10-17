from .channels import GetEarningChannels
from .manage import ManageChannelTask, UpdateEarningSettings
from .rewards import ClaimChannelReward, GetEarningTasks, ResolveEarningClaim

EARNING_USE_CASES = (
    GetEarningChannels,
    ManageChannelTask,
    UpdateEarningSettings,
    ClaimChannelReward,
    GetEarningTasks,
    ResolveEarningClaim,
)
