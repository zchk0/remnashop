from datetime import datetime
from typing import List, Optional, Protocol, TypeVar, Union
from uuid import UUID

from packaging.version import Version

from src.application.dto import (
    PlanSnapshotDto,
    RemnaSubscriptionDto,
    SquadInfoDto,
    SubscriptionDto,
    UserDto,
)
from src.core.types import RemnaDeviceDto, RemnaUserDto
from src.core.utils.panel_identity import PanelUserRef

T = TypeVar("T", SubscriptionDto, RemnaSubscriptionDto)


class Remnawave(Protocol):
    api_version: int

    async def try_connection(self) -> Version: ...

    async def create_user(
        self,
        user: UserDto,
        plan: Optional[PlanSnapshotDto] = None,
        subscription: Optional[SubscriptionDto] = None,
        *,
        short_uuid: Optional[str] = None,
    ) -> RemnaUserDto: ...

    async def update_user_subscription(
        self,
        uuid: PanelUserRef,
        plan: Optional[PlanSnapshotDto] = None,
        subscription: Optional[SubscriptionDto] = None,
        reset_traffic: bool = False,
    ) -> RemnaUserDto: ...

    async def update_user_description(
        self, uuid: PanelUserRef, description: str
    ) -> RemnaUserDto: ...

    async def update_user_email(self, uuid: PanelUserRef, email: str) -> RemnaUserDto: ...

    async def update_user_traffic_limit(
        self,
        uuid: PanelUserRef,
        traffic_limit_bytes: int,
    ) -> RemnaUserDto: ...

    async def update_user_device_limit(
        self,
        uuid: PanelUserRef,
        device_limit: int,
    ) -> RemnaUserDto: ...

    async def update_user_expire_at(
        self,
        uuid: PanelUserRef,
        expire_at: datetime,
    ) -> RemnaUserDto: ...

    async def update_user_internal_squads(
        self,
        uuid: PanelUserRef,
        squad_ids: list[UUID],
    ) -> RemnaUserDto: ...

    async def update_user_external_squad(
        self,
        uuid: PanelUserRef,
        squad_id: Optional[UUID],
    ) -> RemnaUserDto: ...

    async def enable_user(self, uuid: PanelUserRef) -> None: ...

    async def disable_user(self, uuid: PanelUserRef) -> None: ...

    async def delete_user(self, uuid: PanelUserRef) -> bool: ...

    async def get_user_by_uuid(self, uuid: PanelUserRef) -> Optional[RemnaUserDto]: ...

    async def get_user_by_username(self, username: str) -> Optional[RemnaUserDto]: ...

    async def get_user_by_short_uuid(self, short_uuid: str) -> Optional[RemnaUserDto]: ...

    async def get_users_by_telegram_id(self, telegram_id: int) -> List[RemnaUserDto]: ...

    async def get_users_by_email(self, email: str) -> List[RemnaUserDto]: ...

    async def get_all_users(self, limit: int, offset: int) -> List[RemnaUserDto]: ...

    async def get_devices(self, uuid: PanelUserRef) -> List[RemnaDeviceDto]: ...

    async def delete_device(self, user_uuid: PanelUserRef, hwid: str) -> Optional[int]: ...

    async def delete_all_devices(self, user_uuid: PanelUserRef) -> None: ...

    async def drop_connections(self, user_uuid: PanelUserRef) -> None: ...

    async def reset_traffic(self, uuid: PanelUserRef) -> Optional[RemnaUserDto]: ...

    async def revoke_subscription(self, uuid: PanelUserRef) -> Optional[RemnaUserDto]: ...

    async def get_squads_available(self) -> bool: ...

    async def get_internal_squads(self) -> List[SquadInfoDto]: ...

    async def get_external_squads(self) -> List[SquadInfoDto]: ...

    def apply_sync(
        self,
        target: T,
        source: Union[SubscriptionDto, RemnaSubscriptionDto],
    ) -> T: ...
