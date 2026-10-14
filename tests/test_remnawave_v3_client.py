import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from packaging.version import Version
from pydantic import ValidationError
from remnapy.enums import ErrorCode
from remnapy.exceptions import BadRequestError, ConflictError, ServerError, UnauthorizedError

from src.infrastructure.remnawave_v3 import (
    CreateUser,
    PanelV3ResponseError,
    RemnawaveV3Client,
    UpdateUser,
)

_SQUAD = "617dd034-2cf1-41b6-bf15-85e7bfc5e60b"
_TIME = "2030-01-01T00:00:00Z"


def _user(user_id: int = 42) -> dict[str, Any]:
    return {
        "id": user_id,
        "shortUuid": f"short-{user_id}",
        "username": f"user-{user_id}",
        "status": "ACTIVE",
        "expireAt": _TIME,
        "subscriptionUrl": f"https://sub.example.org/short-{user_id}",
        "trafficLimitBytes": 0,
        "trafficLimitStrategy": "NO_RESET",
        "hwidDeviceLimit": 2,
        "activeInternalSquads": [{"uuid": _SQUAD, "name": "squad"}],
        "externalSquadUuid": None,
        "createdAt": _TIME,
        "updatedAt": _TIME,
        "userTraffic": {
            "usedTrafficBytes": 1234,
            "lifetimeUsedTrafficBytes": 5678,
            "onlineAt": None,
            "firstConnectedAt": None,
            "lastConnectedNodeUuid": None,
        },
        "trojanPassword": "private-vpn-password",
        "ssPassword": "private-vpn-password",
        "vlessUuid": _SQUAD,
    }


@dataclass
class _Panel:
    client: RemnawaveV3Client
    responses: list[httpx.Response]
    requests: list[httpx.Request]

    def reply(self, payload: Any = None, *, status: int = 200, wrap: bool = True) -> None:
        if payload is None:
            response = httpx.Response(status)
        else:
            response = httpx.Response(status, json={"response": payload} if wrap else payload)
        self.responses.append(response)


@pytest.fixture
async def panel() -> AsyncIterator[_Panel]:
    requests: list[httpx.Request] = []
    responses: list[httpx.Response] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert responses, "Unexpected extra request"
        return responses.pop(0)

    async with httpx.AsyncClient(
        base_url="https://panel.example.org/api",
        transport=httpx.MockTransport(handle),
        headers={"Authorization": "Bearer test-token", "X-Api-Key": "test-proxy-key"},
        cookies={"proxy": "test-cookie"},
    ) as http:
        yield _Panel(RemnawaveV3Client(http), responses, requests)
    assert not responses, "An expected response was not consumed"


async def test_reads_numeric_id_without_user_uuid_and_preserves_auth(panel: _Panel) -> None:
    panel.reply(_user())
    user = await panel.client.get_user_by_id(42)

    assert user is not None
    assert user.id == 42
    assert user.uuid is None
    assert "uuid" not in user.model_dump()
    assert user.active_internal_squads[0].uuid == UUID(_SQUAD)
    assert user.user_traffic.used_traffic_bytes == 1234
    request = panel.requests[0]
    assert request.url.path == "/api/users/42"
    assert request.headers["Authorization"] == "Bearer test-token"
    assert request.headers["X-Api-Key"] == "test-proxy-key"
    assert "proxy=test-cookie" in request.headers["Cookie"]


async def test_create_sends_no_user_uuid_and_no_unset_fields(panel: _Panel) -> None:
    panel.reply(_user(), status=201)
    user = await panel.client.create_user(
        CreateUser(username="user-42", expire_at=datetime(2030, 1, 1, tzinfo=UTC))
    )

    assert user.id == 42
    assert panel.requests[0].method == "POST"
    assert json.loads(panel.requests[0].content) == {"username": "user-42", "expireAt": _TIME}


async def test_patch_preserves_omitted_fields_and_explicit_squad_removal(panel: _Panel) -> None:
    panel.reply(_user())
    panel.reply(_user())
    await panel.client.update_user(UpdateUser(id=42, traffic_limit_bytes=10000))
    await panel.client.update_user(
        UpdateUser(id=42, external_squad_uuid=None, active_internal_squads=[])
    )

    assert [json.loads(request.content) for request in panel.requests] == [
        {"id": 42, "trafficLimitBytes": 10000},
        {"id": 42, "externalSquadUuid": None, "activeInternalSquads": []},
    ]
    assert all(request.method == "PATCH" for request in panel.requests)


@pytest.mark.parametrize("extra", [{"uuid": _SQUAD}, {"id": 42}, {"userUuid": _SQUAD}])
def test_create_rejects_deprecated_identifiers(extra: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        CreateUser(username="user-42", expire_at=_TIME, **extra)


@pytest.mark.parametrize("user_id", [0, -1, True, "42", 42.5, UUID(_SQUAD)])
async def test_invalid_user_ids_are_rejected_before_http(panel: _Panel, user_id: Any) -> None:
    with pytest.raises(ValidationError):
        await panel.client.get_user_by_id(user_id)
    with pytest.raises(ValidationError):
        UpdateUser(id=user_id, description="test")
    assert not panel.requests


@pytest.mark.parametrize(
    "fields",
    [
        {"uuid": _SQUAD},
        {"status": "EXPIRED"},
        {"traffic_limit_bytes": -1},
        {"traffic_limit_bytes": None},
        {"active_internal_squads": None},
        {"expire_at": None},
    ],
)
def test_patch_rejects_invalid_fields(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        UpdateUser(id=42, **fields)


async def test_delete_accepts_204_without_parsing_a_body(panel: _Panel) -> None:
    panel.reply(status=204)
    assert await panel.client.delete_user(42)
    assert panel.requests[0].method == "DELETE"
    assert panel.requests[0].url.path == "/api/users/42"


async def test_missing_user_is_not_confused_with_auth_failure(panel: _Panel) -> None:
    panel.reply({"message": "Not found", "errorCode": "UNKNOWN"}, status=404, wrap=False)
    assert await panel.client.get_user_by_id(42) is None
    panel.reply({"message": "Not found", "errorCode": "UNKNOWN"}, status=404, wrap=False)
    assert not await panel.client.delete_user(42)
    panel.reply({"message": "Unauthorized", "errorCode": "UNKNOWN"}, status=401, wrap=False)
    with pytest.raises(UnauthorizedError):
        await panel.client.get_user_by_id(42)


async def test_telegram_search_reads_all_cursor_pages(panel: _Panel) -> None:
    panel.reply({"users": [_user(42)], "nextCursor": "42", "hasMore": True})
    panel.reply({"users": [_user(99)], "nextCursor": None, "hasMore": False})
    users = await panel.client.get_users_by_telegram_id(123456)

    assert [user.id for user in users] == [42, 99]
    assert [dict(request.url.params) for request in panel.requests] == [
        {"size": "250", "telegramId": "123456"},
        {"size": "250", "telegramId": "123456", "cursor": "42"},
    ]
    assert all(request.url.path == "/api/users/stream" for request in panel.requests)


async def test_email_search_uses_stream_and_encodes_query_parameters(panel: _Panel) -> None:
    panel.reply({"users": [], "nextCursor": None, "hasMore": False})
    assert await panel.client.get_users_by_email("test+vpn@example.org") == []
    request = panel.requests[0]
    assert request.url.path == "/api/users/stream"
    assert request.url.params["email"] == "test+vpn@example.org"
    assert b"test%2Bvpn%40example.org" in request.url.query


@pytest.mark.parametrize("cursor", [None, "oops", "42.0", "0", "-42", "٤٢"])
async def test_invalid_cursors_stop_pagination(panel: _Panel, cursor: Any) -> None:
    panel.reply({"users": [_user()], "nextCursor": cursor, "hasMore": True})
    with pytest.raises(PanelV3ResponseError):
        await panel.client.get_users_by_telegram_id(123456)
    assert len(panel.requests) == 1


async def test_repeated_cursor_stops_instead_of_looping(panel: _Panel) -> None:
    panel.reply({"users": [_user()], "nextCursor": "42", "hasMore": True})
    panel.reply({"users": [_user()], "nextCursor": "42", "hasMore": True})
    with pytest.raises(PanelV3ResponseError, match="advance"):
        await panel.client.get_users_by_telegram_id(123456)
    assert len(panel.requests) == 2


async def test_offset_pagination_is_available_for_existing_import_workflow(panel: _Panel) -> None:
    panel.reply({"users": [_user()], "total": 1000})
    assert len(await panel.client.get_all_users(500, 250)) == 1
    assert dict(panel.requests[0].url.params) == {"size": "500", "start": "250"}


@pytest.mark.parametrize("size", [0, 1001, True])
async def test_page_size_validation_prevents_invalid_requests(panel: _Panel, size: Any) -> None:
    with pytest.raises(ValidationError):
        await panel.client.get_all_users(size)
    assert not panel.requests


@pytest.mark.parametrize(
    "method, action",
    [
        ("enable_user", "enable"),
        ("disable_user", "disable"),
        ("reset_traffic", "reset-traffic"),
        ("revoke_subscription", "revoke"),
    ],
)
async def test_user_actions_use_numeric_ids(panel: _Panel, method: str, action: str) -> None:
    panel.reply(_user())
    user = await getattr(panel.client, method)(42)
    assert user.id == 42
    assert panel.requests[0].method == "POST"
    assert panel.requests[0].url.path == f"/api/users/42/actions/{action}"


async def test_hwid_reads_and_deletes_use_user_id(panel: _Panel) -> None:
    panel.reply(
        {
            "total": 1,
            "devices": [
                {
                    "userId": 42,
                    "hwid": "abcdefghij",
                    "createdAt": _TIME,
                    "updatedAt": _TIME,
                }
            ],
        }
    )
    panel.reply({"total": 0, "devices": []})
    panel.reply({"total": 0, "devices": []})
    result = await panel.client.get_devices(42)
    assert result.devices[0].user_id == 42
    assert panel.requests[0].url.path == "/api/hwid/devices/42"
    assert (await panel.client.delete_device(42, "abcdefghij")).total == 0
    assert (await panel.client.delete_all_devices(42)).total == 0
    assert [json.loads(request.content) for request in panel.requests[1:]] == [
        {"userId": 42, "hwid": "abcdefghij"},
        {"userId": 42},
    ]
    assert [request.url.path for request in panel.requests[1:]] == [
        "/api/hwid/devices/delete",
        "/api/hwid/devices/delete-all",
    ]


async def test_drop_connections_keeps_union_discriminators_and_accepts_202(panel: _Panel) -> None:
    panel.reply(status=202)
    await panel.client.drop_connections(42)
    assert panel.requests[0].url.path == "/api/connections/drop"
    assert json.loads(panel.requests[0].content) == {
        "dropBy": {"by": "userIds", "userIds": [42]},
        "targetNodes": {"target": "allNodes"},
    }


@pytest.mark.parametrize("status, payload", [(200, {"isDeleted": True}), (202, None), (204, {})])
async def test_delete_does_not_silently_accept_old_or_async_responses(
    panel: _Panel, status: int, payload: Any
) -> None:
    panel.reply(payload, status=status)
    with pytest.raises(PanelV3ResponseError):
        await panel.client.delete_user(42)


@pytest.mark.parametrize(
    "status, payload, error",
    [
        (
            400,
            {"message": "Invalid request", "statusCode": 400, "errors": [{"path": ["id"]}]},
            BadRequestError,
        ),
        (
            400,
            {
                "message": "Username exists",
                "errorCode": ErrorCode.USER_USERNAME_ALREADY_EXISTS.value,
            },
            ConflictError,
        ),
        (500, {"message": "Internal error", "errorCode": "UNKNOWN"}, ServerError),
    ],
)
async def test_errors_remain_typed_and_writes_are_not_retried(
    panel: _Panel, status: int, payload: dict[str, Any], error: type[Exception]
) -> None:
    panel.reply(payload, status=status, wrap=False)
    with pytest.raises(error) as failure:
        await panel.client.create_user(CreateUser(username="user-42", expire_at=_TIME))
    assert failure.value.status_code == status
    assert len(panel.requests) == 1


async def test_timeout_does_not_replay_creation() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ReadTimeout("Response lost", request=request)

    async with httpx.AsyncClient(
        base_url="https://panel.example.org/api", transport=httpx.MockTransport(handle)
    ) as http:
        with pytest.raises(httpx.ReadTimeout):
            await RemnawaveV3Client(http).create_user(
                CreateUser(username="user-42", expire_at=_TIME)
            )
    assert len(requests) == 1


@pytest.mark.parametrize("payload", [{}, {"response": {}}, {"response": _user() | {"id": "bad"}}])
async def test_invalid_responses_do_not_expose_vpn_credentials(panel: _Panel, payload: Any) -> None:
    panel.reply(payload, wrap=False)
    with pytest.raises(PanelV3ResponseError) as failure:
        await panel.client.get_user_by_id(42)
    assert "private-vpn-password" not in str(failure.value)
    assert failure.value.__cause__ is None


async def test_connection_probe_rejects_v2_and_accepts_target_version(panel: _Panel) -> None:
    panel.reply({"version": "2.8.1"})
    with pytest.raises(ValueError, match="requires panel 3.x"):
        await panel.client.try_connection()
    panel.reply({"version": "3.4.5"})
    assert await panel.client.try_connection() == Version("3.4.5")
    assert all(request.url.path == "/api/system/metadata" for request in panel.requests)
