from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

from remnapy.enums.users import TrafficLimitStrategy

from src.application.use_cases.subscription.commands.management import (
    AddSubscriptionDuration,
    AddSubscriptionDurationDto,
)
from src.core.enums import SubscriptionStatus
from src.infrastructure.services.remnawave import RemnawaveImpl


class _FakeUnitOfWork:
    def __init__(self) -> None:
        self.commit = AsyncMock()

    async def __aenter__(self) -> "_FakeUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        return None


def _remnawave_service() -> tuple[RemnawaveImpl, AsyncMock]:
    update_user = AsyncMock(return_value=SimpleNamespace())
    sdk = SimpleNamespace(users=SimpleNamespace(update_user=update_user))
    return RemnawaveImpl(sdk), update_user


async def test_granular_updates_send_only_the_requested_field() -> None:
    service, update_user = _remnawave_service()
    user_uuid = uuid4()
    squad_uuid = uuid4()
    expire_at = datetime(2026, 8, 10, tzinfo=UTC)

    await service.update_user_traffic_limit(user_uuid, 10_000)
    await service.update_user_device_limit(user_uuid, 3)
    await service.update_user_expire_at(user_uuid, expire_at)
    await service.update_user_internal_squads(user_uuid, [squad_uuid])
    await service.update_user_external_squad(user_uuid, None)

    payloads = [
        call.args[0].model_dump(mode="json", by_alias=True, exclude_unset=True)
        for call in update_user.await_args_list
    ]
    assert payloads == [
        {"uuid": str(user_uuid), "trafficLimitBytes": 10_000},
        {"uuid": str(user_uuid), "hwidDeviceLimit": 3},
        {"uuid": str(user_uuid), "expireAt": "2026-08-10T00:00:00Z"},
        {"uuid": str(user_uuid), "activeInternalSquads": [str(squad_uuid)]},
        {"uuid": str(user_uuid), "externalSquadUuid": None},
    ]


async def test_subscription_update_does_not_touch_panel_owned_user_fields() -> None:
    service, update_user = _remnawave_service()
    user_uuid = uuid4()
    internal_squad = uuid4()
    external_squad = uuid4()
    subscription = SimpleNamespace(
        expire_at=datetime(2026, 8, 10, tzinfo=UTC),
        status=SubscriptionStatus.ACTIVE,
        traffic_limit_strategy=TrafficLimitStrategy.NO_RESET,
        traffic_limit=100,
        device_limit=5,
        tag="PAID",
        internal_squads=[internal_squad],
        external_squad=external_squad,
    )

    await service.update_user_subscription(user_uuid, subscription=subscription)

    request = update_user.await_args.args[0]
    assert request.model_fields_set == {
        "uuid",
        "expire_at",
        "status",
        "traffic_limit_strategy",
        "traffic_limit_bytes",
        "hwid_device_limit",
        "tag",
        "active_internal_squads",
        "external_squad_uuid",
    }
    assert "description" not in request.model_fields_set
    assert "email" not in request.model_fields_set
    assert "telegram_id" not in request.model_fields_set


async def test_duration_change_uses_expiration_only_update() -> None:
    user_uuid = UUID("00000000-0000-0000-0000-000000000001")
    target_user = SimpleNamespace(id=7, remna_name="user-7")
    subscription = SimpleNamespace(
        expire_at=datetime(2026, 8, 10, tzinfo=UTC),
        user_remna_id=user_uuid,
    )
    remnawave = SimpleNamespace(update_user_expire_at=AsyncMock())
    subscription_dao = SimpleNamespace(
        get_current=AsyncMock(return_value=subscription),
        update=AsyncMock(),
    )
    use_case = AddSubscriptionDuration(
        uow=_FakeUnitOfWork(),
        user_dao=SimpleNamespace(get_by_id=AsyncMock(return_value=target_user)),
        subscription_dao=subscription_dao,
        remnawave=remnawave,
    )

    await use_case.system(AddSubscriptionDurationDto(user_id=7, days=3))

    remnawave.update_user_expire_at.assert_awaited_once_with(
        user_uuid,
        datetime(2026, 8, 13, tzinfo=UTC),
    )
