"""Explicit v3 client; the running v2 integration is not switched by importing it."""

from collections.abc import AsyncIterator
from typing import Annotated, Any, TypeVar
from urllib.parse import quote

import httpx
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from remnapy.exceptions import NotFoundError
from remnapy.exceptions.handler import handle_api_error

from src.core.utils.panel_identity import PanelApiVersionMismatchError

from .models import (
    CreateUser,
    HwidDevices,
    Metadata,
    SubscriptionInfo,
    UpdateUser,
    User,
    UserFilters,
    UserId,
    UsersPage,
    UsersStreamPage,
)

_ResponseT = TypeVar("_ResponseT", bound=BaseModel)
_USER_ID: TypeAdapter[int] = TypeAdapter(UserId)
_PAGE_SIZE: TypeAdapter[int] = TypeAdapter(Annotated[int, Field(strict=True, ge=1, le=1000)])
_OFFSET: TypeAdapter[int] = TypeAdapter(Annotated[int, Field(strict=True, ge=0)])


class PanelV3ResponseError(RuntimeError):
    """The response cannot be used safely with the v3 contract."""


class RemnawaveV3Client:
    def __init__(self, client: httpx.AsyncClient) -> None:
        if not client.base_url.path.rstrip("/").endswith("/api"):
            raise ValueError("The client base URL must end with /api")
        # Authentication, proxy headers, cookies, timeouts and lifecycle belong to the caller.
        self._client = client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        response = await self._client.request(method, path, json=body, params=params)
        if response.is_error:
            handle_api_error(response)
        return response

    async def _read(
        self,
        model: type[_ResponseT],
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> _ResponseT:
        response = await self._request(method, path, body=body, params=params)
        if response.status_code not in (200, 201):
            raise PanelV3ResponseError(f"Unexpected HTTP status for {method} {path}")
        try:
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("response"), dict):
                raise ValueError("Missing response object")
            return model.model_validate(payload["response"])
        except (ValueError, ValidationError):
            # Never include the raw payload: user responses also contain VPN credentials.
            raise PanelV3ResponseError(f"Invalid response for {method} {path}") from None

    async def _empty(
        self, method: str, path: str, expected_status: int, *, body: dict[str, Any] | None = None
    ) -> None:
        response = await self._request(method, path, body=body)
        if response.status_code != expected_status or response.content:
            raise PanelV3ResponseError(f"Unexpected response for {method} {path}")

    @staticmethod
    def _user_path(user_id: int) -> str:
        return f"users/{_USER_ID.validate_python(user_id)}"

    async def try_connection(self) -> Version:
        metadata = await self._read(Metadata, "GET", "system/metadata")
        try:
            version = Version(metadata.version)
        except InvalidVersion:
            raise PanelV3ResponseError("Panel returned an invalid version") from None
        if version.major != 3:
            raise PanelApiVersionMismatchError(
                f"The v3 client requires panel 3.x; received {version}"
            )
        return version

    async def create_user(self, request: CreateUser) -> User:
        return await self._read(
            User,
            "POST",
            "users",
            body=request.model_dump(mode="json", by_alias=True, exclude_unset=True),
        )

    async def update_user(self, request: UpdateUser) -> User:
        return await self._read(
            User,
            "PATCH",
            "users",
            body=request.model_dump(mode="json", by_alias=True, exclude_unset=True),
        )

    async def _get_user(self, path: str) -> User | None:
        try:
            return await self._read(User, "GET", path)
        except NotFoundError:
            return None

    async def get_user_by_id(self, user_id: int) -> User | None:
        return await self._get_user(self._user_path(user_id))

    async def get_user_by_username(self, username: str) -> User | None:
        return await self._get_user(f"users/by-username/{quote(username, safe='')}")

    async def get_user_by_short_uuid(self, short_uuid: str) -> User | None:
        return await self._get_user(f"users/by-short-uuid/{quote(short_uuid, safe='')}")

    async def get_subscription_info(self, short_uuid: str) -> SubscriptionInfo:
        return await self._read(SubscriptionInfo, "GET", f"sub/{quote(short_uuid, safe='')}/info")

    async def delete_user(self, user_id: int) -> bool:
        try:
            await self._empty("DELETE", self._user_path(user_id), 204)
        except NotFoundError:
            return False
        return True

    async def get_all_users(self, limit: int, offset: int = 0) -> list[User]:
        page = await self._read(
            UsersPage,
            "GET",
            "users",
            params={
                "size": _PAGE_SIZE.validate_python(limit),
                "start": _OFFSET.validate_python(offset),
            },
        )
        return page.users

    async def iter_users(
        self, filters: UserFilters | None = None, *, size: int = 250
    ) -> AsyncIterator[User]:
        params: dict[str, Any] = {"size": _PAGE_SIZE.validate_python(size)}
        if filters is not None:
            params.update(filters.model_dump(mode="json", by_alias=True, exclude_none=True))
        cursor = 0
        while True:
            page = await self._read(UsersStreamPage, "GET", "users/stream", params=params)
            next_cursor = self._next_cursor(page, cursor) if page.has_more else None
            for user in page.users:
                yield user
            if next_cursor is None:
                return
            cursor = next_cursor
            params["cursor"] = cursor

    @staticmethod
    def _next_cursor(page: UsersStreamPage, previous: int) -> int:
        cursor = page.next_cursor
        if cursor is None or not cursor.isascii() or not cursor.isdecimal():
            raise PanelV3ResponseError("The users stream returned an invalid nextCursor")
        value = int(cursor)
        if value <= previous or not page.users:
            raise PanelV3ResponseError("The users stream did not advance its cursor")
        return value

    async def get_users_by_telegram_id(self, telegram_id: int) -> list[User]:
        return [user async for user in self.iter_users(UserFilters(telegram_id=telegram_id))]

    async def get_users_by_email(self, email: str) -> list[User]:
        return [user async for user in self.iter_users(UserFilters(email=email))]

    async def enable_user(self, user_id: int) -> User:
        return await self._read(User, "POST", f"{self._user_path(user_id)}/actions/enable")

    async def disable_user(self, user_id: int) -> User:
        return await self._read(User, "POST", f"{self._user_path(user_id)}/actions/disable")

    async def reset_traffic(self, user_id: int) -> User:
        return await self._read(User, "POST", f"{self._user_path(user_id)}/actions/reset-traffic")

    async def revoke_subscription(self, user_id: int) -> User:
        return await self._read(User, "POST", f"{self._user_path(user_id)}/actions/revoke")

    async def get_devices(self, user_id: int) -> HwidDevices:
        return await self._read(
            HwidDevices, "GET", f"hwid/devices/{_USER_ID.validate_python(user_id)}"
        )

    async def delete_device(self, user_id: int, hwid: str) -> HwidDevices:
        return await self._read(
            HwidDevices,
            "POST",
            "hwid/devices/delete",
            body={"userId": _USER_ID.validate_python(user_id), "hwid": hwid},
        )

    async def delete_all_devices(self, user_id: int) -> HwidDevices:
        return await self._read(
            HwidDevices,
            "POST",
            "hwid/devices/delete-all",
            body={"userId": _USER_ID.validate_python(user_id)},
        )

    async def drop_connections(self, user_id: int) -> None:
        await self._empty(
            "POST",
            "connections/drop",
            202,
            body={
                "dropBy": {"by": "userIds", "userIds": [_USER_ID.validate_python(user_id)]},
                "targetNodes": {"target": "allNodes"},
            },
        )
