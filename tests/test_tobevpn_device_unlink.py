from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from remnapy.enums import TrafficLimitStrategy

from src.application.common import Notifier, Remnawave
from src.application.common.dao import DeviceSessionDao, LinkedDeviceDao, SubscriptionDao, UserDao
from src.application.common.uow import UnitOfWork
from src.application.dto import PlanSnapshotDto, SubscriptionDto
from src.application.dto.device import LinkedDeviceDto
from src.web.endpoints.devices import DeviceAuthContext, get_device_auth_context, router


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    subscription = SubscriptionDto(
        panel_user_id=42,
        traffic_limit=100,
        device_limit=3,
        traffic_limit_strategy=TrafficLimitStrategy.NO_RESET,
        expire_at=datetime(2035, 1, 1, tzinfo=UTC),
        url="https://example.com/sub/current",
        plan_snapshot=PlanSnapshotDto.test(),
    )
    panel_user = SimpleNamespace(
        id=42,
        uuid=None,
        telegram_id=101,
        short_uuid="current",
        subscription_url=subscription.url,
    )
    revoked_user = SimpleNamespace(
        **{
            **vars(panel_user),
            "short_uuid": "new",
            "subscription_url": "https://example.com/sub/new",
        }
    )
    current_device = LinkedDeviceDto(
        device_id="phone", telegram_id=101, panel_user_id=42, short_uuid="current"
    )
    device_dao = SimpleNamespace(
        lock_binding_by_telegram_id=AsyncMock(),
        get_by_device_id=AsyncMock(
            return_value=LinkedDeviceDto(device_id="router", telegram_id=101)
        ),
        get_by_telegram_id=AsyncMock(return_value=[current_device]),
        unlink=AsyncMock(return_value=True),
        upsert=AsyncMock(),
    )
    session_dao = SimpleNamespace(revoke=AsyncMock(return_value=True))
    subscription_dao = SimpleNamespace(get_current=AsyncMock(return_value=subscription))
    user_dao = SimpleNamespace(get_by_telegram_id=AsyncMock(return_value=SimpleNamespace(id=1)))
    remnawave = SimpleNamespace(
        get_users_by_telegram_id=AsyncMock(return_value=[panel_user]),
        get_devices=AsyncMock(
            return_value=[SimpleNamespace(hwid="phone"), SimpleNamespace(hwid="router")]
        ),
        delete_device=AsyncMock(return_value=1),
        revoke_subscription=AsyncMock(return_value=revoked_user),
    )
    notifier = SimpleNamespace(notify_user=AsyncMock())
    uow = SimpleNamespace(commit=AsyncMock())
    sync_subscription = AsyncMock(
        return_value=(replace(subscription, url=revoked_user.subscription_url), True)
    )
    monkeypatch.setattr(
        "src.web.endpoints.devices._sync_subscription_from_panel_user", sync_subscription
    )
    deps = {
        LinkedDeviceDao: device_dao,
        DeviceSessionDao: session_dao,
        SubscriptionDao: subscription_dao,
        UserDao: user_dao,
        Remnawave: remnawave,
        Notifier: notifier,
        UnitOfWork: uow,
    }

    class FakeContainer:
        async def get(self, dependency, component=""):
            return deps[dependency]

    app = FastAPI()

    @app.middleware("http")
    async def inject_container(request, call_next):
        request.state.dishka_container = FakeContainer()
        return await call_next(request)

    app.dependency_overrides[get_device_auth_context] = lambda: DeviceAuthContext(
        device_id="phone", telegram_id=101, panel_user_id=42, short_uuid="current"
    )
    app.include_router(router)
    return SimpleNamespace(
        client=TestClient(app),
        subscription=subscription,
        panel_user=panel_user,
        device_dao=device_dao,
        session_dao=session_dao,
        remnawave=remnawave,
        notifier=notifier,
        uow=uow,
        sync_subscription=sync_subscription,
    )


@pytest.mark.parametrize(
    "reset_subscription", [None, True, False], ids=["omitted", "true", "false"]
)
def test_unlink_another_device(api: SimpleNamespace, reset_subscription: bool | None) -> None:
    body = {"device_id": "router"}
    if reset_subscription is not None:
        body["reset_subscription"] = reset_subscription

    response = api.client.post("/api/device/unlink", json=body)

    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    data = result["data"]
    should_reset = reset_subscription is not False
    expected_url = "https://example.com/sub/new" if should_reset else api.subscription.url
    assert data["remaining_devices"] == 1
    assert data["subscription_url"] == expected_url
    assert data["subscription"]["url"] == expected_url
    assert data["current_plan"]["name"] == api.subscription.plan_snapshot.name
    assert data["subscription_link_reset"] is should_reset
    assert data["bot_subscription_updated"] is should_reset
    assert data["bot_subscription_changed"] is should_reset
    assert data["linked_devices_updated"] == int(should_reset)
    assert data["notification_sent"] is should_reset
    api.remnawave.delete_device.assert_awaited_once_with(42, "router")
    api.device_dao.unlink.assert_awaited_once_with("router", 101)
    api.session_dao.revoke.assert_awaited_once_with("router")
    api.uow.commit.assert_awaited_once()
    if should_reset:
        api.remnawave.revoke_subscription.assert_awaited_once_with(42)
        api.sync_subscription.assert_awaited_once()
        api.notifier.notify_user.assert_awaited_once()
        updated_device = api.device_dao.upsert.call_args.args[0]
        assert updated_device.device_id == "phone"
        assert updated_device.short_uuid == "new"
    else:
        api.remnawave.revoke_subscription.assert_not_awaited()
        api.sync_subscription.assert_not_awaited()
        api.device_dao.upsert.assert_not_awaited()
        api.notifier.notify_user.assert_not_awaited()
        assert api.panel_user.short_uuid == "current"


@pytest.mark.parametrize(
    "reset_subscription", [None, True, False], ids=["omitted", "true", "false"]
)
def test_unlink_current_device_keeps_existing_no_reset_behavior(
    api: SimpleNamespace, reset_subscription: bool | None
) -> None:
    body = {} if reset_subscription is None else {"reset_subscription": reset_subscription}

    response = api.client.post("/api/device/unlink", json=body)

    assert response.status_code == 200
    assert response.json()["data"]["subscription_link_reset"] is False
    api.remnawave.delete_device.assert_awaited_once_with(42, "phone")
    api.device_dao.unlink.assert_awaited_once_with("phone", 101)
    api.session_dao.revoke.assert_awaited_once_with("phone")
    api.remnawave.revoke_subscription.assert_not_awaited()
    api.notifier.notify_user.assert_not_awaited()


@pytest.mark.parametrize(
    "body",
    [
        {"device_id": "someone-elses-device", "reset_subscription": False},
        {"device_id": "router", "telegram_id": 202, "reset_subscription": False},
    ],
)
def test_disabling_reset_still_checks_device_ownership(api: SimpleNamespace, body: dict) -> None:
    response = api.client.post("/api/device/unlink", json=body)

    assert response.status_code == 403
    api.remnawave.delete_device.assert_not_awaited()
    api.device_dao.unlink.assert_not_awaited()
    api.session_dao.revoke.assert_not_awaited()
    api.remnawave.revoke_subscription.assert_not_awaited()
    api.uow.commit.assert_not_awaited()
