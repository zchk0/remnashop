from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from remnapy import RemnawaveSDK
from remnapy.enums import TrafficLimitStrategy

from src.application.common import BotService, Remnawave
from src.application.common.dao import SubscriptionDao, UserDao
from src.application.dto import PlanSnapshotDto, SubscriptionDto
from src.application.use_cases.plan.queries.match import MatchPlan
from src.application.use_cases.user.queries.plans import GetAvailablePlans
from src.core.enums import PlanType
from src.web.endpoints.devices import DeviceAuthContext, get_device_auth_context, router


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    now = datetime(2030, 10, 7, 12, tzinfo=UTC)
    monkeypatch.setattr("src.core.utils.time.datetime_now", lambda: now)
    plan = PlanSnapshotDto.test()
    plan.traffic_limit = 100
    plan.device_limit = 3
    plan.type = PlanType.BOTH
    plan.traffic_limit_strategy = TrafficLimitStrategy.MONTH_ROLLING
    subscription = SubscriptionDto(
        user_remna_id=UUID("12345678-1234-1234-1234-123456789abc"),
        traffic_limit=100,
        device_limit=3,
        traffic_limit_strategy=TrafficLimitStrategy.MONTH_ROLLING,
        expire_at=datetime(2031, 1, 1, tzinfo=UTC),
        url="https://example.com/sub/short",
        plan_snapshot=plan,
        created_at=datetime(2030, 10, 3, tzinfo=UTC),
    )
    panel_user = SimpleNamespace(
        traffic_limit_bytes=100 * 1024**3,
        traffic_limit_strategy=TrafficLimitStrategy.MONTH_ROLLING,
        created_at=datetime(2030, 1, 15, tzinfo=UTC),
        last_traffic_reset_at=datetime(2030, 10, 3, 12, tzinfo=UTC),
    )
    fetch_user = AsyncMock(return_value=panel_user)
    info_data = {
        "is_found": True,
        "user": {"short_uuid": "short", "traffic_limit_strategy": "MONTH_ROLLING"},
        "links": ["vless://existing-link"],
        "subscription_url": subscription.url,
    }
    fetch_info = AsyncMock(
        return_value=SimpleNamespace(model_dump=lambda **kwargs: info_data.copy())
    )
    sdk_fetch_user = AsyncMock(return_value=panel_user)
    subscription_dao = SimpleNamespace(get_current=AsyncMock(return_value=subscription))
    deps = {
        UserDao: SimpleNamespace(
            get_by_telegram_id=AsyncMock(
                return_value=SimpleNamespace(id=1, name="User", username=None, is_privileged=False)
            )
        ),
        SubscriptionDao: subscription_dao,
        GetAvailablePlans: SimpleNamespace(system=AsyncMock(return_value=[])),
        MatchPlan: SimpleNamespace(system=AsyncMock(return_value=None)),
        BotService: SimpleNamespace(),
        Remnawave: SimpleNamespace(get_user_by_uuid=fetch_user),
        RemnawaveSDK: SimpleNamespace(
            subscription=SimpleNamespace(get_subscription_info_by_short_uuid=fetch_info),
            users=SimpleNamespace(get_user_by_short_uuid=sdk_fetch_user),
        ),
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
        telegram_id=123, short_uuid="short"
    )
    app.include_router(router)
    return SimpleNamespace(
        client=TestClient(app),
        panel_user=panel_user,
        subscription=subscription,
        subscription_dao=subscription_dao,
        fetch_user=fetch_user,
        sdk_fetch_user=sdk_fetch_user,
        fetch_info=fetch_info,
    )


@pytest.mark.parametrize(
    ("path", "container_path"),
    [
        ("/api/subscription/current-plan", ("data", "subscription")),
        ("/api/panel/sub/short/info", ("response", "user")),
    ],
)
def test_subscription_info_exposes_utc_date_and_seconds(
    api: SimpleNamespace, path: str, container_path: tuple[str, str]
) -> None:
    response = api.client.get(path)

    assert response.status_code == 200
    data = response.json()[container_path[0]][container_path[1]]
    expected = datetime(2030, 10, 15, 0, 10, tzinfo=UTC)
    assert datetime.fromisoformat(data["next_traffic_reset_at"]) == expected
    assert data["next_traffic_reset_at_ts"] == int(expected.timestamp())
    if path.endswith("/info"):
        assert response.json()["response"]["links"] == ["vless://existing-link"]
    else:
        assert data["url"] == api.subscription.url


@pytest.mark.parametrize("path", ["/api/subscription/current-plan", "/api/panel/sub/short/info"])
@pytest.mark.parametrize("no_reset", [True, False])
def test_subscription_without_automatic_traffic_reset_returns_null(
    api: SimpleNamespace, path: str, no_reset: bool
) -> None:
    if no_reset:
        api.subscription.traffic_limit_strategy = TrafficLimitStrategy.NO_RESET
        api.panel_user.traffic_limit_strategy = TrafficLimitStrategy.NO_RESET
    else:
        api.subscription.traffic_limit = 0
        api.panel_user.traffic_limit_bytes = 0

    response = api.client.get(path)

    assert response.status_code == 200
    result = response.json()
    data = result["response"]["user"] if path.endswith("/info") else result["data"]["subscription"]
    assert data["next_traffic_reset_at"] is None
    assert data["next_traffic_reset_at_ts"] is None


@pytest.mark.parametrize("path", ["/api/subscription/current-plan", "/api/panel/sub/short/info"])
def test_unavailable_panel_does_not_break_subscription_info(
    api: SimpleNamespace, path: str
) -> None:
    api.fetch_user.side_effect = TimeoutError("Panel unavailable")
    api.sdk_fetch_user.side_effect = TimeoutError("Panel unavailable")

    response = api.client.get(path)

    assert response.status_code == 200
    result = response.json()
    data = result["response"]["user"] if path.endswith("/info") else result["data"]["subscription"]
    assert data["next_traffic_reset_at"] is None
    assert data["next_traffic_reset_at_ts"] is None


def test_legacy_info_rejects_another_subscription_before_fetching(api: SimpleNamespace) -> None:
    response = api.client.get("/api/panel/sub/another-subscription/info")

    assert response.status_code == 403
    api.fetch_info.assert_not_awaited()
    api.sdk_fetch_user.assert_not_awaited()


def test_no_subscription_still_returns_null_subscription(api: SimpleNamespace) -> None:
    api.subscription_dao.get_current.return_value = None

    response = api.client.get("/api/subscription/current-plan")

    assert response.status_code == 200
    assert response.json()["data"]["subscription"] is None
    api.fetch_user.assert_not_awaited()
