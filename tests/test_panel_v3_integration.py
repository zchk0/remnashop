import hashlib
import hmac
import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from adaptix import Retort
from aiogram_dialog import BgManagerFactory
from dishka import make_async_container
from fastapi import FastAPI, HTTPException
from pydantic import SecretStr
from remnapy import RemnawaveSDK
from remnapy.enums import TrafficLimitStrategy
from starlette.requests import Request

from src.application.common import Remnawave
from src.application.common.dao import LinkedDeviceDao
from src.application.dto import PlanSnapshotDto, RemnaSubscriptionDto, SubscriptionDto, UserDto
from src.application.dto.promocode import PromocodeActivationDto
from src.application.services.remnawave import RemnaWebhookService
from src.application.use_cases.promocode.commands.activate import (
    ActivatePromocode,
    _PermanentActivationError,
)
from src.application.use_cases.remnawave.commands.synchronization import (
    SyncRemnaUser,
    SyncRemnaUserDto,
)
from src.application.use_cases.subscription.commands.purchase import (
    ActivateTrialSubscription,
    ActivateTrialSubscriptionDto,
    PurchaseSubscription,
    PurchaseSubscriptionDto,
)
from src.core.config import AppConfig
from src.core.config.remnawave import RemnawaveConfig
from src.core.enums import (
    PlanType,
    PromocodeRemoteAction,
    PromocodeRewardType,
    PurchaseType,
    SubscriptionStatus,
)
from src.core.utils.panel_identity import panel_user_ref, remote_user_ref, subscription_ref
from src.infrastructure.di.providers import get_aiogram_providers, get_taskiq_providers
from src.infrastructure.di.providers.services import ServicesProvider
from src.infrastructure.remnawave_v3.client import RemnawaveV3Client
from src.infrastructure.remnawave_v3.compat import PanelClient
from src.infrastructure.remnawave_v3.models import User
from src.infrastructure.services.remnawave import RemnawaveImpl
from src.infrastructure.services.remnawave_v3 import RemnawaveV3Impl
from src.web.endpoints.devices import (
    AuthRequest,
    DeviceAuthContext,
    _build_panel_user_data,
    _create_auth_token,
    _get_panel_device_ids,
    get_device_auth_context,
    save_email,
)
from src.web.endpoints.remnawave import _process_remnawave_webhook


def _user(**changes):
    data = {
        "id": 42,
        "shortUuid": "short-42",
        "username": "test-user",
        "status": "ACTIVE",
        "expireAt": "2030-01-01T00:00:00Z",
        "subscriptionUrl": "https://example.org/sub/short-42",
        "trafficLimitBytes": 1073741824,
        "trafficLimitStrategy": "NO_RESET",
        "userTraffic": {"usedTrafficBytes": 100, "lifetimeUsedTrafficBytes": 300},
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-10-14T00:00:00Z",
        "telegramId": 123,
        "hwidDeviceLimit": 2,
        "activeInternalSquads": [],
    }
    return data | changes


def _plan():
    return PlanSnapshotDto(
        id=1,
        name="Trial",
        type=PlanType.BOTH,
        traffic_limit=1,
        device_limit=2,
        duration=7,
        traffic_limit_strategy=TrafficLimitStrategy.NO_RESET,
    )


def _subscription(legacy=None, numeric=42):
    return SubscriptionDto(
        id=15,
        user_id=7,
        user_remna_id=legacy,
        panel_user_id=numeric,
        traffic_limit=1,
        device_limit=2,
        traffic_limit_strategy=TrafficLimitStrategy.NO_RESET,
        expire_at=datetime(2030, 1, 1, tzinfo=UTC),
        url="old-url",
        plan_snapshot=_plan(),
    )


class _Uow:
    def __init__(self):
        self.commit = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


@pytest.fixture
async def panel():
    requests = []
    responses = []

    def handle(request):
        requests.append(request)
        assert responses, "Unexpected request"
        return responses.pop(0)

    async with httpx.AsyncClient(
        base_url="https://panel.example.org/api", transport=httpx.MockTransport(handle)
    ) as http:
        sdk = RemnawaveSDK(http)
        v3 = RemnawaveV3Client(http)
        yield SimpleNamespace(
            service=RemnawaveV3Impl(sdk, v3),
            client=PanelClient(sdk, v3, 3),
            requests=requests,
            responses=responses,
        )
    assert not responses


def _reply(panel, body=None, status=200):
    panel.responses.append(
        httpx.Response(status, json={"response": body} if body is not None else None)
    )


def test_default_config_keeps_v2_and_provider_selects_explicit_version():
    cfg = RemnawaveConfig(token="test-token", webhook_secret="test-webhook")
    assert cfg.api_version == 2
    provider = ServicesProvider()
    for version, cls in ((2, RemnawaveImpl), (3, RemnawaveV3Impl)):
        result = provider.remnawave(
            SimpleNamespace(),
            SimpleNamespace(v3=object()),
            SimpleNamespace(remnawave=SimpleNamespace(api_version=version)),
        )
        assert type(result) is cls


def test_numeric_references_do_not_depend_on_uuid():
    sub = _subscription(legacy=uuid4())
    assert subscription_ref(sub) == 42
    assert remote_user_ref(User.model_validate(_user())) == 42
    assert panel_user_ref(None, 42) == 42
    with pytest.raises(ValueError):
        panel_user_ref(None, None)


@pytest.mark.parametrize("numeric", [0, -1, True, "42"])
def test_invalid_numeric_identity_is_rejected(numeric):
    with pytest.raises(ValueError):
        panel_user_ref(None, numeric)


async def test_v2_resolves_numeric_reference_before_patching():
    legacy = uuid4()
    sdk = SimpleNamespace(
        users=SimpleNamespace(
            get_user_by_id=AsyncMock(return_value=SimpleNamespace(uuid=legacy)),
            update_user=AsyncMock(return_value=SimpleNamespace()),
        )
    )
    await RemnawaveImpl(sdk).update_user_traffic_limit(42, 500)
    sdk.users.get_user_by_id.assert_awaited_once_with(42)
    assert sdk.users.update_user.await_args.args[0].model_dump(exclude_unset=True) == {
        "uuid": legacy,
        "traffic_limit_bytes": 500,
    }


async def test_v3_refuses_unmapped_uuid_without_sending_request(panel):
    with pytest.raises(ValueError, match="backfill"):
        await panel.service.update_user_device_limit(uuid4(), 3)
    assert not panel.requests


async def test_trial_saves_numeric_id_and_no_fabricated_uuid(panel):
    _reply(panel, _user(), status=201)
    use_case = ActivateTrialSubscription(
        _Uow(),
        SimpleNamespace(set_trial_available=AsyncMock()),
        SimpleNamespace(create=AsyncMock()),
        panel.service,
        SimpleNamespace(publish=AsyncMock()),
    )
    local_user = UserDto(id=7, name="User", telegram_id=123)
    await use_case._execute(local_user, ActivateTrialSubscriptionDto(user=local_user, plan=_plan()))
    saved = use_case.subscription_dao.create.await_args.kwargs["subscription"]
    assert saved.user_remna_id is None
    assert saved.panel_user_id == 42
    assert saved.is_trial
    payload = json.loads(panel.requests[0].content)
    assert payload["telegramId"] == 123 and "uuid" not in payload
    assert Retort().load(Retort().dump(saved), SubscriptionDto).panel_user_id == 42


async def test_v3_subscription_update_uses_id_and_preserves_other_fields(panel):
    _reply(panel, _user())
    sub = _subscription(legacy=uuid4())
    await panel.service.update_user_subscription(subscription_ref(sub), subscription=sub)
    payload = json.loads(panel.requests[0].content)
    assert payload["id"] == 42 and "uuid" not in payload
    assert "description" not in payload and "email" not in payload and "telegramId" not in payload
    assert payload["activeInternalSquads"] == [] and payload["externalSquadUuid"] is None


@pytest.mark.parametrize(
    ("purchase_type", "has_trial"),
    [
        (PurchaseType.NEW, False),
        (PurchaseType.RENEW, False),
        (PurchaseType.CHANGE, False),
        (PurchaseType.NEW, True),
    ],
)
async def test_v3_purchase_renewal_and_trial_conversion_keep_numeric_id(
    panel, purchase_type, has_trial
):
    is_creation = purchase_type == PurchaseType.NEW and not has_trial
    _reply(panel, _user(), status=201 if is_creation else 200)
    if not is_creation:
        _reply(panel, _user())  # Reset traffic after a paid renewal/change.
    user = UserDto(id=7, name="User", telegram_id=123)
    sub = None if is_creation else replace(_subscription(legacy=uuid4()), is_trial=has_trial)
    subscription_dao = SimpleNamespace(
        create=AsyncMock(), update=AsyncMock(), update_status=AsyncMock()
    )
    use_case = PurchaseSubscription(
        _Uow(),
        SimpleNamespace(set_trial_available=AsyncMock(), update=AsyncMock()),
        subscription_dao,
        panel.service,
    )
    transaction = SimpleNamespace(id=1, plan_snapshot=_plan(), purchase_type=purchase_type)
    await use_case._execute(
        user, PurchaseSubscriptionDto(user=user, transaction=transaction, subscription=sub)
    )
    if purchase_type == PurchaseType.RENEW:
        saved = subscription_dao.update.await_args.args[0]
        assert saved.panel_user_id == 42
    else:
        saved = subscription_dao.create.await_args.kwargs["subscription"]
        assert saved.panel_user_id == 42 and saved.user_remna_id is None
    first = json.loads(panel.requests[0].content)
    assert "uuid" not in first
    if not is_creation:
        assert first["id"] == 42


def test_sync_preserves_legacy_alias_for_same_id_and_clears_it_after_recreation():
    legacy = uuid4()
    sub = _subscription(legacy=legacy)
    remote = RemnaSubscriptionDto.from_remna_user(User.model_validate(_user()))
    service = RemnawaveImpl.__new__(RemnawaveImpl)
    service.apply_sync(sub, remote)
    assert sub.user_remna_id == legacy and sub.panel_user_id == 42
    service.apply_sync(sub, replace(remote, panel_user_id=43))
    assert sub.user_remna_id is None and sub.panel_user_id == 43


async def test_device_hwid_list_uses_numeric_id(panel):
    _reply(panel, {"total": 0, "devices": []})
    user = User.model_validate(_user())
    assert await _get_panel_device_ids(user, panel.service) == []
    assert panel.requests[0].url.path == "/api/hwid/devices/42"
    assert _build_panel_user_data(user)["panel_user_id"] == 42
    assert _build_panel_user_data(user)["panel_user_uuid"] is None


async def test_promocode_recovers_created_v3_user_by_reserved_marker():
    marker = uuid4().hex
    remote = User.model_validate(_user(shortUuid=marker))
    sub = _subscription(numeric=None)
    activation = PromocodeActivationDto(
        promocode_id=1,
        user_id=7,
        activated_at=datetime.now(UTC),
        code_snapshot="PROMO",
        reward_type_snapshot=PromocodeRewardType.SUBSCRIPTION,
        request_id=uuid4(),
        remote_action=PromocodeRemoteAction.CREATE_SUBSCRIPTION,
        target_subscription_id=15,
        target_short_uuid=marker,
    )
    use_case = ActivatePromocode.__new__(ActivatePromocode)
    use_case.remnawave = SimpleNamespace(
        get_user_by_short_uuid=AsyncMock(return_value=remote), create_user=AsyncMock()
    )
    use_case.subscription_dao = SimpleNamespace(
        get_by_id=AsyncMock(return_value=sub), update=AsyncMock()
    )
    use_case.promocode_dao = SimpleNamespace(set_activation_panel_id=AsyncMock())
    await use_case._apply_remote_action(UserDto(id=7, name="User", telegram_id=123), activation)
    use_case.remnawave.create_user.assert_not_awaited()
    use_case.remnawave.get_user_by_short_uuid.assert_awaited_once_with(marker)
    assert sub.panel_user_id == 42 and sub.user_remna_id is None
    use_case.promocode_dao.set_activation_panel_id.assert_awaited_once_with(
        activation.request_id, 42
    )


async def test_promocode_rejects_marker_owned_by_another_telegram_user():
    marker = uuid4().hex
    use_case = ActivatePromocode.__new__(ActivatePromocode)
    use_case.remnawave = SimpleNamespace(
        get_user_by_short_uuid=AsyncMock(
            return_value=User.model_validate(_user(shortUuid=marker, telegramId=456))
        ),
        create_user=AsyncMock(),
    )
    with pytest.raises(_PermanentActivationError, match="identity"):
        await use_case._create_reserved_subscription(
            UserDto(id=7, name="User", telegram_id=123),
            _subscription(numeric=None),
            SimpleNamespace(target_short_uuid=marker),
        )
    use_case.remnawave.create_user.assert_not_awaited()


async def test_promocode_duration_keeps_numeric_target_and_partial_update():
    sub = _subscription(legacy=uuid4())
    use_case = ActivatePromocode.__new__(ActivatePromocode)
    use_case.remnawave = SimpleNamespace(
        update_user_expire_at=AsyncMock(return_value=User.model_validate(_user()))
    )
    await use_case._update_reserved_subscription(
        sub, SimpleNamespace(reward_type_snapshot=PromocodeRewardType.DURATION)
    )
    use_case.remnawave.update_user_expire_at.assert_awaited_once_with(42, sub.expire_at)


def _request(body, signature):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [
                (b"x-remnawave-signature", signature.encode()),
                (b"x-remnawave-timestamp", b"2026-10-14T00:00:00Z"),
            ],
        },
        receive,
    )


async def test_v3_webhook_validates_signature_before_accepting_numeric_user():
    raw = {
        "event": "user.expiration",
        "timestamp": "2026-10-14T00:00:00Z",
        "data": _user(),
        "meta": {"expiration": -24},
    }
    body = json.dumps(raw).encode()
    signature = hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
    service = SimpleNamespace(handle_user_event=AsyncMock())
    config = SimpleNamespace(
        remnawave=SimpleNamespace(api_version=3, webhook_secret=SecretStr("test-secret"))
    )
    response = await _process_remnawave_webhook(
        _request(body, signature), config, service, SimpleNamespace(publish=AsyncMock())
    )
    assert response.status_code == 200
    assert service.handle_user_event.await_args.args[1].id == 42
    assert service.handle_user_event.await_args.kwargs["expiration_hours"] == -24
    with pytest.raises(HTTPException) as error:
        await _process_remnawave_webhook(
            _request(body, "invalid"), config, service, SimpleNamespace(publish=AsyncMock())
        )
    assert error.value.status_code == 401
    assert service.handle_user_event.await_count == 1


async def test_deleted_history_does_not_unlink_another_current_v3_subscription():
    service = RemnaWebhookService.__new__(RemnaWebhookService)
    history = _subscription(numeric=42)
    current = replace(history, id=16, panel_user_id=43, user_remna_id=None)
    service.uow = _Uow()
    service.subscription_dao = SimpleNamespace(
        get_by_remna_id=AsyncMock(return_value=history),
        get_current=AsyncMock(return_value=current),
        update=AsyncMock(),
    )
    service.user_dao = SimpleNamespace(clear_current_subscription=AsyncMock())
    await service._process_delete_subscription(User.model_validate(_user()))
    service.subscription_dao.get_by_remna_id.assert_awaited_once_with(42)
    service.user_dao.clear_current_subscription.assert_not_awaited()
    assert history.status == SubscriptionStatus.DELETED


async def test_auth_request_saves_server_resolved_numeric_user():
    remote = User.model_validate(_user())
    sdk = SimpleNamespace(
        users=SimpleNamespace(get_user_by_username=AsyncMock(return_value=remote))
    )
    device_dao = SimpleNamespace(get_by_device_id=AsyncMock(return_value=None), upsert=AsyncMock())
    auth_dao = SimpleNamespace(get_by_token=AsyncMock(return_value=None), create=AsyncMock())
    uow = _Uow()
    result = await _create_auth_token(
        AuthRequest(device_id="device-a", panel_user_id=42),
        DeviceAuthContext(device_id="device-a"),
        device_dao,
        auth_dao,
        uow,
        sdk,
    )
    assert result["success"]
    saved = auth_dao.create.await_args.args[0]
    assert saved.panel_user_id == 42 and saved.panel_user_uuid is None


async def test_auth_request_rejects_numeric_user_of_another_device():
    remote = User.model_validate(_user())
    sdk = SimpleNamespace(
        users=SimpleNamespace(get_user_by_username=AsyncMock(return_value=remote))
    )
    device_dao = SimpleNamespace(get_by_device_id=AsyncMock(return_value=None), upsert=AsyncMock())
    auth_dao = SimpleNamespace(get_by_token=AsyncMock(return_value=None), create=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await _create_auth_token(
            AuthRequest(device_id="device-a", panel_user_id=99),
            DeviceAuthContext(device_id="device-a"),
            device_dao,
            auth_dao,
            _Uow(),
            sdk,
        )
    assert error.value.status_code == 403
    auth_dao.create.assert_not_awaited()


async def test_auth_request_cannot_reassign_another_device_token():
    auth_dao = SimpleNamespace(
        get_by_token=AsyncMock(return_value=SimpleNamespace(device_id="device-b")),
        create=AsyncMock(),
    )
    with pytest.raises(HTTPException) as error:
        await _create_auth_token(
            AuthRequest(device_id="device-a", auth_token="existing-token"),
            DeviceAuthContext(device_id="device-a"),
            SimpleNamespace(),
            auth_dao,
            _Uow(),
            SimpleNamespace(),
        )
    assert error.value.status_code == 403
    auth_dao.create.assert_not_awaited()


async def test_auth_request_never_marks_primary_account_as_anonymous_cleanup_target():
    sdk = SimpleNamespace(users=SimpleNamespace(get_user_by_username=AsyncMock(return_value=None)))
    device_dao = SimpleNamespace(get_by_device_id=AsyncMock(return_value=None), upsert=AsyncMock())
    auth_dao = SimpleNamespace(get_by_token=AsyncMock(return_value=None), create=AsyncMock())
    await _create_auth_token(
        AuthRequest(device_id="device-a", panel_user_id=42),
        DeviceAuthContext(device_id="device-a", telegram_id=123, panel_user_id=42),
        device_dao,
        auth_dao,
        _Uow(),
        sdk,
    )
    saved = auth_dao.create.await_args.args[0]
    assert saved.panel_user_id is None and saved.panel_user_uuid is None


async def test_v3_public_subscription_info_uses_public_route_and_contract(panel):
    data = {
        "isFound": True,
        "user": {
            "shortUuid": "short-42",
            "daysLeft": 10,
            "trafficUsed": "100 B",
            "trafficLimit": "1 GB",
            "lifetimeTrafficUsed": "300 B",
            "trafficUsedBytes": "100",
            "trafficLimitBytes": "1073741824",
            "lifetimeTrafficUsedBytes": "300",
            "username": "test-user",
            "expiresAt": "2030-01-01T00:00:00Z",
            "isActive": True,
            "userStatus": "ACTIVE",
            "trafficLimitStrategy": "NO_RESET",
        },
        "links": [],
        "ssConfLinks": {},
        "subscriptionUrl": "https://example.org/sub/short-42",
    }
    _reply(panel, data)
    result = await panel.client.subscription.get_subscription_info_by_short_uuid("short-42")
    assert result.model_dump()["user"]["short_uuid"] == "short-42"
    assert panel.requests[0].url.path == "/api/sub/short-42/info"


async def test_modified_v3_event_cannot_rebind_another_current_subscription():
    local_user = UserDto(id=7, name="User", telegram_id=123)
    current = _subscription(numeric=43)
    use_case = SyncRemnaUser.__new__(SyncRemnaUser)
    use_case.uow = _Uow()
    use_case.user_dao = SimpleNamespace(
        get_by_remna_uuid=AsyncMock(return_value=None),
        get_by_telegram_id=AsyncMock(return_value=local_user),
    )
    use_case.subscription_dao = SimpleNamespace(
        get_current=AsyncMock(return_value=current), update=AsyncMock()
    )
    result = await use_case._execute(
        local_user, SyncRemnaUserDto(User.model_validate(_user()), creating=False)
    )
    assert result is False
    assert current.panel_user_id == 43
    use_case.subscription_dao.update.assert_not_awaited()


async def test_both_application_containers_validate_versioned_dependencies():
    for providers in (get_aiogram_providers, get_taskiq_providers):
        container = make_async_container(
            *providers(), context={AppConfig: AppConfig.get(), BgManagerFactory: object()}
        )
        await container.close()


@pytest.mark.parametrize("linked", [True, False])
async def test_client_can_save_email_using_only_its_device_session(panel, linked):
    device_id = "device-a"
    username = (
        "test-user" if linked else "app_" + hashlib.sha256(device_id.encode()).hexdigest()[:32]
    )
    user = _user(username=username, telegramId=123 if linked else None)
    _reply(panel, user)
    _reply(panel, user | {"email": "test@example.org"})
    response = await _email_request(
        body={"email": "test@example.org"},
        auth=DeviceAuthContext(
            device_id=device_id,
            telegram_id=123 if linked else None,
            panel_user_id=42 if linked else None,
        ),
        remnawave=panel.service,
        remnawave_sdk=panel.client,
    )
    assert response.status_code == 200
    assert response.json() == {"success": True, "data": None}
    assert len(panel.requests) == 2
    lookup = "/api/users/42" if linked else f"/api/users/by-username/{username}"
    assert panel.requests[0].url.path == lookup
    assert panel.requests[1].method == "PATCH"
    assert json.loads(panel.requests[1].content) == {"id": 42, "email": "test@example.org"}


@pytest.mark.parametrize(
    "claimed_identity", [{"panel_user_id": 99}, {"panel_user_uuid": str(uuid4())}]
)
async def test_email_identity_cannot_override_current_device_user(panel, claimed_identity):
    _reply(panel, _user())
    response = await _email_request(
        body={"email": "test@example.org", **claimed_identity},
        auth=DeviceAuthContext(device_id="device-a", telegram_id=123, panel_user_id=42),
        remnawave=panel.service,
        remnawave_sdk=panel.client,
    )
    assert response.status_code == 403
    assert len(panel.requests) == 1


async def test_email_only_request_also_works_with_v2_user():
    legacy_uuid = uuid4()
    user = SimpleNamespace(uuid=legacy_uuid, id=42)
    remnawave = SimpleNamespace(get_user_by_uuid=AsyncMock(return_value=user))
    update = AsyncMock()
    response = await _email_request(
        body={"email": "test@example.org"},
        auth=DeviceAuthContext(device_id="device-a", telegram_id=123, panel_user_id=42),
        remnawave=remnawave,
        remnawave_sdk=SimpleNamespace(users=SimpleNamespace(update_user_fields=update)),
    )
    assert response.status_code == 200
    assert response.json() == {"success": True, "data": None}
    remnawave.get_user_by_uuid.assert_awaited_once_with(42)
    update.assert_awaited_once_with(legacy_uuid, email="test@example.org")


async def _email_request(*, body, auth, remnawave, remnawave_sdk):
    deps = {
        LinkedDeviceDao: SimpleNamespace(),
        Remnawave: remnawave,
        PanelClient: remnawave_sdk,
    }
    app = FastAPI()

    @app.middleware("http")
    async def inject_container(request, call_next):
        request.state.dishka_container = SimpleNamespace(
            get=AsyncMock(side_effect=lambda dependency, component="": deps[dependency])
        )
        return await call_next(request)

    app.dependency_overrides[get_device_auth_context] = lambda: auth
    app.post("/api/device/save-email")(save_email)
    async with httpx.AsyncClient(
        base_url="https://bot.example.org", transport=httpx.ASGITransport(app)
    ) as client:
        return await client.post("/api/device/save-email", json=body)
