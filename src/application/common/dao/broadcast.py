from contextlib import AbstractAsyncContextManager
from typing import Optional, Protocol, runtime_checkable
from uuid import UUID

from src.application.dto import BroadcastDto, BroadcastMessageDto
from src.core.enums import BroadcastStatus


@runtime_checkable
class BroadcastDao(Protocol):
    async def create(self, broadcast: BroadcastDto) -> BroadcastDto: ...

    async def get_by_task_id(self, task_id: UUID) -> Optional[BroadcastDto]: ...

    async def get_all(self) -> list[BroadcastDto]: ...

    async def get_delivered_telegram_ids(self, campaign_id: UUID) -> list[int]: ...

    async def record_delivery(
        self,
        campaign_id: UUID,
        telegram_id: int,
        *,
        broadcast_message_id: Optional[int] = None,
        message_id: Optional[int] = None,
    ) -> None: ...

    def lock_campaign(self, campaign_id: UUID) -> AbstractAsyncContextManager[None]: ...

    async def lock_campaign_transaction(self, campaign_id: UUID) -> None: ...

    async def clear_finished_campaign(self, campaign_id: UUID) -> None: ...

    async def update_status(self, task_id: UUID, status: BroadcastStatus) -> None: ...

    async def add_messages(
        self,
        task_id: UUID,
        messages: list[BroadcastMessageDto],
    ) -> list[BroadcastMessageDto]: ...

    async def update_stats(self, task_id: UUID, success_count: int, failed_count: int) -> None: ...

    async def update_total_count(self, task_id: UUID, total: int) -> None: ...

    async def delete_old(self, days: int = 14) -> int: ...

    async def bulk_update_messages(self, messages: list[BroadcastMessageDto]) -> None: ...
