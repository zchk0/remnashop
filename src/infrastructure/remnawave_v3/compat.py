"""Version selection for callers that also need the panel's non-user controllers."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from remnapy import RemnawaveSDK
from remnapy.exceptions import ApiErrorResponse, NotFoundError
from remnapy.models import CreateUserRequestDto, UpdateUserRequestDto, UserResponseDto
from remnapy.models.subscription import GetSubscriptionInfoResponseDto

from src.core.types import RemnaUserDto
from src.core.utils.panel_identity import PanelUserRef

from .client import RemnawaveV3Client
from .models import CreateUser, SubscriptionInfo, UpdateUser, User


@dataclass
class PanelUsersList:
    root: list[RemnaUserDto]

    def __len__(self) -> int:
        return len(self.root)

    def __getitem__(self, index: int) -> RemnaUserDto:
        return self.root[index]

    def __iter__(self) -> Iterator[RemnaUserDto]:
        return iter(self.root)


class PanelUsers:
    def __init__(self, sdk: RemnawaveSDK, v3: RemnawaveV3Client, api_version: int) -> None:
        self.sdk = sdk
        self.v3 = v3
        self.api_version = api_version

    @staticmethod
    def numeric_id(reference: PanelUserRef) -> int:
        if type(reference) is not int or reference <= 0:
            raise ValueError("Panel 3.x requires a saved numeric user ID; backfill is missing")
        return reference

    async def legacy_uuid(self, reference: PanelUserRef) -> UUID:
        if isinstance(reference, UUID):
            return reference
        user = await self.sdk.users.get_user_by_id(reference)
        return user.uuid

    async def create_user(self, request: CreateUserRequestDto) -> RemnaUserDto:
        if self.api_version == 2:
            return await self.sdk.users.create_user(request)
        fields = request.model_dump(mode="json", exclude_unset=True, exclude_none=True)
        fields.pop("uuid", None)  # User UUIDs are removed by v3, VPN credentials are kept.
        return await self.v3.create_user(CreateUser.model_validate(fields))

    async def update_user_fields(self, reference: PanelUserRef, **fields: Any) -> RemnaUserDto:
        if self.api_version == 2:
            return await self.sdk.users.update_user(
                UpdateUserRequestDto(uuid=await self.legacy_uuid(reference), **fields)
            )
        return await self.v3.update_user(UpdateUser(id=self.numeric_id(reference), **fields))

    async def get_user_by_uuid(self, reference: PanelUserRef) -> RemnaUserDto:
        if self.api_version == 2:
            if isinstance(reference, int):
                return await self.sdk.users.get_user_by_id(reference)
            return await self.sdk.users.get_user_by_uuid(reference)
        return self._found(await self.v3.get_user_by_id(self.numeric_id(reference)))

    async def get_user_by_username(self, username: str) -> RemnaUserDto:
        if self.api_version == 2:
            return await self.sdk.users.get_user_by_username(username)
        return self._found(await self.v3.get_user_by_username(username))

    async def get_user_by_short_uuid(self, short_uuid: str) -> RemnaUserDto:
        if self.api_version == 2:
            return await self.sdk.users.get_user_by_short_uuid(short_uuid)
        return self._found(await self.v3.get_user_by_short_uuid(short_uuid))

    @staticmethod
    def _found(user: User | None) -> User:
        if user is None:
            raise NotFoundError(404, ApiErrorResponse(message="Panel user not found"))
        return user

    async def get_users_by_telegram_id(self, telegram_id: int | str) -> PanelUsersList:
        if self.api_version == 2:
            result = await self.sdk.users.get_users_by_telegram_id(telegram_id)
            return PanelUsersList(list(result.root))
        return PanelUsersList(list(await self.v3.get_users_by_telegram_id(int(telegram_id))))

    async def enable_user(self, reference: PanelUserRef) -> UserResponseDto | User:
        if self.api_version == 2:
            return await self.sdk.users.enable_user(await self.legacy_uuid(reference))
        return await self.v3.enable_user(self.numeric_id(reference))

    async def disable_user(self, reference: PanelUserRef) -> UserResponseDto | User:
        if self.api_version == 2:
            return await self.sdk.users.disable_user(await self.legacy_uuid(reference))
        return await self.v3.disable_user(self.numeric_id(reference))


class PanelSubscription:
    def __init__(self, sdk: RemnawaveSDK, v3: RemnawaveV3Client, api_version: int) -> None:
        self.sdk = sdk
        self.v3 = v3
        self.api_version = api_version

    async def get_subscription_info_by_short_uuid(
        self, short_uuid: str
    ) -> GetSubscriptionInfoResponseDto | SubscriptionInfo:
        if self.api_version == 2:
            return await self.sdk.subscription.get_subscription_info_by_short_uuid(short_uuid)
        return await self.v3.get_subscription_info(short_uuid)


class PanelClient:
    def __init__(self, sdk: RemnawaveSDK, v3: RemnawaveV3Client, api_version: int) -> None:
        self.api_version = api_version
        self.v3 = v3
        self.users = PanelUsers(sdk, v3, api_version)
        # These entities retain UUIDs in v3 and use the same resource routes.
        self.system = sdk.system
        self.nodes = sdk.nodes
        self.hosts = sdk.hosts
        self.inbounds = sdk.inbounds
        self.internal_squads = sdk.internal_squads
        self.external_squads = sdk.external_squads
        self.subscription = PanelSubscription(sdk, v3, api_version)
