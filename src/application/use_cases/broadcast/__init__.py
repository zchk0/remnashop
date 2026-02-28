from typing import Final

from src.application.common import Interactor

from .commands.lifecycle import CancelBroadcast, DeleteBroadcast, FinishBroadcast, StartBroadcast
from .commands.messages import (
    BulkUpdateBroadcastMessages,
    InitializeBroadcastMessages,
    UpdateBroadcastMessageStatus,
)
from .queries.audience import GetBroadcastAudienceCount, GetBroadcastAudienceUsers

BROADCAST_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    GetBroadcastAudienceCount,
    GetBroadcastAudienceUsers,
    StartBroadcast,
    DeleteBroadcast,
    CancelBroadcast,
    InitializeBroadcastMessages,
    UpdateBroadcastMessageStatus,
    FinishBroadcast,
    BulkUpdateBroadcastMessages,
)
