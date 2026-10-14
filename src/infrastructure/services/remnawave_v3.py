from datetime import datetime
from typing import Any
from uuid import UUID

from loguru import logger
from packaging.version import Version
from remnapy import RemnawaveSDK
from remnapy.exceptions import ConflictError, NotFoundError

from src.application.dto import PlanSnapshotDto, SubscriptionDto, UserDto
from src.core.types import RemnaDeviceDto, RemnaUserDto
from src.core.utils.panel_identity import PanelUserRef
from src.infrastructure.remnawave_v3.client import RemnawaveV3Client
from src.infrastructure.remnawave_v3.compat import PanelUsers
from src.infrastructure.remnawave_v3.models import CreateUser, UpdateUser, User

from .remnawave import RemnawaveImpl


class RemnawaveV3Impl(RemnawaveImpl):
    api_version = 3

    def __init__(self, sdk: RemnawaveSDK, client: RemnawaveV3Client) -> None:
        super().__init__(sdk)
        self.client = client

    async def try_connection(self) -> Version:
        return await self.client.try_connection()

    async def create_user(
        self,
        user: UserDto,
        plan: PlanSnapshotDto | None = None,
        subscription: SubscriptionDto | None = None,
        *,
        short_uuid: str | None = None,
    ) -> User:
        fields = self._build_create_request(user, plan, subscription).model_dump(
            mode="json", exclude_unset=True
        )
        fields.pop("uuid", None)
        if short_uuid is not None:
            fields["short_uuid"] = short_uuid
        request = CreateUser.model_validate(fields)
        try:
            return await self.client.create_user(request)
        except ConflictError:
            existing = await self.client.get_user_by_short_uuid(short_uuid) if short_uuid else None
            # A reserved short UUID identifies this particular creation, including lost replies.
            if (
                short_uuid is not None
                and existing is not None
                and existing.short_uuid == short_uuid
                and existing.telegram_id == request.telegram_id
            ):
                return existing
            raise

    async def _update(self, reference: PanelUserRef, **fields: Any) -> User:
        return await self.client.update_user(
            UpdateUser(id=PanelUsers.numeric_id(reference), **fields)
        )

    async def update_user_subscription(
        self,
        uuid: PanelUserRef,
        plan: PlanSnapshotDto | None = None,
        subscription: SubscriptionDto | None = None,
        reset_traffic: bool = False,
    ) -> User:
        # The shared builder supplies only subscription fields, preserving panel-owned metadata.
        fields = self._build_update_request(None, plan, subscription).model_dump(
            mode="json", exclude_unset=True
        )
        fields.pop("uuid")
        user = await self._update(uuid, **fields)
        if reset_traffic:
            await self.reset_traffic(uuid)
        return user

    async def update_user_description(self, uuid: PanelUserRef, description: str) -> User:
        return await self._update(uuid, description=description)

    async def update_user_traffic_limit(self, uuid: PanelUserRef, traffic_limit_bytes: int) -> User:
        return await self._update(uuid, traffic_limit_bytes=traffic_limit_bytes)

    async def update_user_device_limit(self, uuid: PanelUserRef, device_limit: int) -> User:
        return await self._update(uuid, hwid_device_limit=device_limit)

    async def update_user_expire_at(self, uuid: PanelUserRef, expire_at: datetime) -> User:
        return await self._update(uuid, expire_at=expire_at)

    async def update_user_internal_squads(self, uuid: PanelUserRef, squad_ids: list[UUID]) -> User:
        return await self._update(uuid, active_internal_squads=squad_ids)

    async def update_user_external_squad(self, uuid: PanelUserRef, squad_id: UUID | None) -> User:
        return await self._update(uuid, external_squad_uuid=squad_id)

    async def get_user_by_uuid(self, uuid: PanelUserRef) -> User | None:
        return await self.client.get_user_by_id(PanelUsers.numeric_id(uuid))

    async def get_user_by_username(self, username: str) -> User | None:
        return await self.client.get_user_by_username(username)

    async def get_user_by_short_uuid(self, short_uuid: str) -> User | None:
        return await self.client.get_user_by_short_uuid(short_uuid)

    async def get_users_by_telegram_id(self, telegram_id: int) -> list[RemnaUserDto]:
        return list(await self.client.get_users_by_telegram_id(telegram_id))

    async def get_users_by_email(self, email: str) -> list[RemnaUserDto]:
        return list(await self.client.get_users_by_email(email))

    async def get_all_users(self, limit: int, offset: int) -> list[RemnaUserDto]:
        return list(await self.client.get_all_users(limit, offset))

    async def enable_user(self, uuid: PanelUserRef) -> None:
        await self.client.enable_user(PanelUsers.numeric_id(uuid))

    async def disable_user(self, uuid: PanelUserRef) -> None:
        await self.client.disable_user(PanelUsers.numeric_id(uuid))

    async def delete_user(self, uuid: PanelUserRef) -> bool:
        return await self.client.delete_user(PanelUsers.numeric_id(uuid))

    async def get_devices(self, user_uuid: PanelUserRef) -> list[RemnaDeviceDto]:
        return list((await self.client.get_devices(PanelUsers.numeric_id(user_uuid))).devices)

    async def delete_device(self, user_uuid: PanelUserRef, hwid_uuid: str) -> int | None:
        try:
            return (
                await self.client.delete_device(PanelUsers.numeric_id(user_uuid), hwid_uuid)
            ).total
        except NotFoundError:
            return None

    async def delete_all_devices(self, user_uuid: PanelUserRef) -> None:
        try:
            await self.client.delete_all_devices(PanelUsers.numeric_id(user_uuid))
        except NotFoundError:
            return

    async def drop_connections(self, user_uuid: PanelUserRef) -> None:
        user_id = PanelUsers.numeric_id(user_uuid)
        try:
            await self.client.drop_connections(user_id)
        except Exception as error:
            logger.warning(f"Failed to drop connections for panel user '{user_id}': {error}")

    async def reset_traffic(self, uuid: PanelUserRef) -> User | None:
        try:
            return await self.client.reset_traffic(PanelUsers.numeric_id(uuid))
        except NotFoundError:
            return None

    async def revoke_subscription(self, uuid: PanelUserRef) -> User | None:
        try:
            return await self.client.revoke_subscription(PanelUsers.numeric_id(uuid))
        except NotFoundError:
            return None
