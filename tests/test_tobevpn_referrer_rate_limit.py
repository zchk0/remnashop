import asyncio
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fakeredis import FakeServer
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI, HTTPException
from redis.asyncio import Redis

from src.application.common.dao import ReferralDao, SettingsDao, UserDao
from src.application.dto import SettingsDto, UserDto
from src.application.use_cases.referral.commands.attachment import AttachReferral
from src.core.constants import TIME_1D
from src.web.endpoints.devices import (
    DeviceAuthContext,
    _enforce_referrer_error_limit,
    get_device_auth_context,
    router,
)


@pytest.fixture
async def api():
    redis = FakeRedis(server=FakeServer(), decode_responses=True)
    users = {
        telegram_id: UserDto(
            id=uid, telegram_id=telegram_id, name=f"User {uid}", referral_code=f"r{uid}"
        )
        for uid, telegram_id in enumerate((101, 202, 303), start=1)
    }
    links = {}
    settings = SettingsDto()
    user_dao = SimpleNamespace(get_by_telegram_id=AsyncMock(side_effect=users.get))
    referral_dao = SimpleNamespace(get_by_referred_id=AsyncMock(side_effect=links.get))

    async def attach(data):
        referrer = next(user for user in users.values() if user.referral_code == data.referral_code)
        links[data.user_id] = SimpleNamespace(referrer=referrer)
        return referrer

    attach_referral = SimpleNamespace(system=AsyncMock(side_effect=attach))
    state = SimpleNamespace(auth=DeviceAuthContext(device_id="phone", telegram_id=101))
    deps = {
        Redis: redis,
        UserDao: user_dao,
        ReferralDao: referral_dao,
        SettingsDao: SimpleNamespace(get=AsyncMock(return_value=settings)),
        AttachReferral: attach_referral,
    }

    class FakeContainer:
        async def get(self, dependency, component=""):
            return deps[dependency]

    app = FastAPI()

    @app.middleware("http")
    async def inject_container(request, call_next):
        request.state.dishka_container = FakeContainer()
        return await call_next(request)

    app.dependency_overrides[get_device_auth_context] = lambda: state.auth
    app.include_router(router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        yield SimpleNamespace(
            client=client,
            redis=redis,
            users=users,
            links=links,
            settings=settings,
            user_dao=user_dao,
            attach=attach_referral.system,
            state=state,
        )
    await redis.aclose()


def error_key(telegram_id=101):
    return f"rate_limit:tobevpn:referrer:errors:{telegram_id}"


async def post_referrer(api, referrer_id=999):
    return await api.client.post("/api/device/referrer", json={"referrer_id": referrer_id})


async def test_twenty_errors_are_allowed_then_next_attempt_is_throttled(api):
    for _ in range(20):
        assert (await post_referrer(api)).status_code == 404
    response = await post_referrer(api, 202)
    assert response.status_code == 429
    assert 1 <= int(response.headers["Retry-After"]) <= TIME_1D
    assert await api.redis.get(error_key()) == "20"
    api.attach.assert_not_awaited()


async def test_success_and_repeated_success_do_not_create_an_error_counter(api):
    response = await post_referrer(api, 202)
    assert response.status_code == 200 and response.json()["data"]["created"]
    for _ in range(30):
        response = await post_referrer(api, 202)
        assert response.status_code == 200 and not response.json()["data"]["created"]
    assert not await api.redis.exists(error_key())
    api.attach.assert_awaited_once()


async def test_existing_assignment_can_be_repeated_even_after_error_budget_is_exhausted(api):
    assert (await post_referrer(api, 202)).status_code == 200
    for _ in range(20):
        assert (await post_referrer(api, 303)).status_code == 409
    assert (await post_referrer(api, 303)).status_code == 429
    response = await post_referrer(api, 202)
    assert response.status_code == 200
    assert not response.json()["data"]["created"]
    assert await api.redis.get(error_key()) == "20"
    api.attach.assert_awaited_once()


async def test_error_budget_is_shared_by_devices_but_isolated_between_telegram_users(api):
    for _ in range(20):
        assert (await post_referrer(api)).status_code == 404
    api.state.auth = DeviceAuthContext(device_id="different-phone", telegram_id=101)
    assert (await post_referrer(api)).status_code == 429
    api.state.auth = DeviceAuthContext(device_id="different-phone", telegram_id=303)
    assert (await post_referrer(api, 202)).status_code == 200
    assert not await api.redis.exists(error_key(303))


async def test_only_first_error_starts_the_window_and_expiry_restores_attempts(api):
    assert (await post_referrer(api)).status_code == 404
    assert TIME_1D - 10 <= await api.redis.ttl(error_key()) <= TIME_1D
    await api.redis.expire(error_key(), 120)
    assert (await post_referrer(api)).status_code == 404
    assert 110 <= await api.redis.ttl(error_key()) <= 120
    assert await api.redis.get(error_key()) == "2"
    await api.redis.expire(error_key(), 0)
    assert (await post_referrer(api)).status_code == 404
    assert await api.redis.get(error_key()) == "1"
    assert TIME_1D - 10 <= await api.redis.ttl(error_key()) <= TIME_1D


async def test_success_after_errors_keeps_the_error_count_and_window(api):
    for _ in range(3):
        assert (await post_referrer(api)).status_code == 404
    await api.redis.expire(error_key(), 120)
    assert (await post_referrer(api, 202)).status_code == 200
    assert await api.redis.get(error_key()) == "3"
    assert 110 <= await api.redis.ttl(error_key()) <= 120


@pytest.mark.parametrize(
    ("scenario", "status_code"),
    [
        ("missing_user", 404),
        ("missing_referrer", 404),
        ("self", 409),
        ("different_referrer", 409),
        ("disabled", 409),
        ("cycle", 409),
        ("attachment_rejected", 409),
    ],
)
async def test_business_errors_consume_one_attempt(api, scenario, status_code):
    referrer_id = 202
    if scenario == "missing_user":
        api.users.pop(101)
    elif scenario == "missing_referrer":
        referrer_id = 999
    elif scenario == "self":
        referrer_id = 101
    elif scenario == "different_referrer":
        api.links[1] = SimpleNamespace(referrer=api.users[303])
    elif scenario == "disabled":
        api.settings.referral.enable = False
    elif scenario == "cycle":
        api.links[2] = SimpleNamespace(referrer=api.users[101])
    elif scenario == "attachment_rejected":
        api.attach.side_effect = None
        api.attach.return_value = None
    assert (await post_referrer(api, referrer_id)).status_code == status_code
    assert await api.redis.get(error_key()) == "1"


@pytest.mark.parametrize("error", [TimeoutError("Panel unavailable"), HTTPException(503)])
async def test_server_errors_do_not_consume_attempts(api, error):
    api.attach.side_effect = error
    assert (await post_referrer(api, 202)).status_code >= 500
    assert not await api.redis.exists(error_key())


async def test_unlinked_session_does_not_create_an_error_counter(api):
    api.state.auth = DeviceAuthContext(device_id="anonymous-device")
    assert (await post_referrer(api, 202)).status_code == 403
    assert not await api.redis.keys("rate_limit:tobevpn:referrer:errors:*")


async def test_parallel_requests_cannot_exceed_the_error_budget(api):
    responses = await asyncio.gather(*(post_referrer(api) for _ in range(40)))
    assert Counter(response.status_code for response in responses) == {404: 20, 429: 20}
    assert await api.redis.get(error_key()) == "20"
    api.attach.assert_not_awaited()


async def test_lua_limit_is_atomic_across_redis_clients():
    server = FakeServer()
    clients = [FakeRedis(server=server), FakeRedis(server=server)]
    try:
        results = await asyncio.gather(
            *(
                _enforce_referrer_error_limit(clients[index % 2], 101, record_error=True)
                for index in range(40)
            ),
            return_exceptions=True,
        )
        assert sum(result is None for result in results) == 20
        assert (
            sum(
                isinstance(result, HTTPException) and result.status_code == 429
                for result in results
            )
            == 20
        )
        assert await clients[0].get(error_key()) == b"20"
    finally:
        await asyncio.gather(*(client.aclose() for client in clients))
