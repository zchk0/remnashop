from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.application.use_cases.promocode.commands.activate import (
    PROMOCODE_ACTIVATION_MAX_ATTEMPTS,
    ActivatePromocode,
    _PermanentActivationError,
    get_promocode_retry_delay,
)
from src.application.use_cases.promocode.queries.validate import ValidatePromocode
from src.core.enums import (
    PromocodeActivationStatus,
    PromocodeRemoteAction,
    PromocodeRewardType,
    SubscriptionStatus,
)


class _FakeUnitOfWork:
    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def __aenter__(self) -> "_FakeUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type:
            await self.rollback()


def _activation(*, attempt_count: int = 0, reset_traffic: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        status=PromocodeActivationStatus.PENDING,
        attempt_count=attempt_count,
        reset_traffic=reset_traffic,
    )


def _use_case(activation: SimpleNamespace) -> tuple[ActivatePromocode, SimpleNamespace]:
    dao = SimpleNamespace(
        get_activation_by_request_id=AsyncMock(return_value=activation),
        record_activation_failure=AsyncMock(),
    )
    use_case = ActivatePromocode.__new__(ActivatePromocode)
    use_case.uow = _FakeUnitOfWork()
    use_case.promocode_dao = dao
    return use_case, dao


def test_promocode_retry_delay_is_bounded() -> None:
    assert get_promocode_retry_delay(1).total_seconds() == 60
    assert get_promocode_retry_delay(4).total_seconds() == 900
    assert get_promocode_retry_delay(100).total_seconds() == 21600


@pytest.mark.asyncio
async def test_transient_failure_is_rescheduled() -> None:
    use_case, dao = _use_case(_activation())

    await use_case._record_activation_error(uuid4(), RuntimeError("temporary"))

    call = dao.record_activation_failure.await_args.kwargs
    assert call["status"] == PromocodeActivationStatus.PENDING
    assert call["attempt_count"] == 1
    assert call["next_retry_at"] is not None


@pytest.mark.asyncio
async def test_exhausted_failure_requires_review() -> None:
    use_case, dao = _use_case(
        _activation(attempt_count=PROMOCODE_ACTIVATION_MAX_ATTEMPTS - 1)
    )

    await use_case._record_activation_error(uuid4(), RuntimeError("still failing"))

    call = dao.record_activation_failure.await_args.kwargs
    assert call["status"] == PromocodeActivationStatus.REQUIRES_REVIEW
    assert call["next_retry_at"] is None


@pytest.mark.asyncio
async def test_reset_traffic_is_not_retried_after_unknown_result() -> None:
    use_case, dao = _use_case(_activation(reset_traffic=True))

    await use_case._record_activation_error(uuid4(), RuntimeError("response lost"))

    call = dao.record_activation_failure.await_args.kwargs
    assert call["status"] == PromocodeActivationStatus.REQUIRES_REVIEW
    assert call["attempt_count"] == 1
    assert call["next_retry_at"] is None


@pytest.mark.asyncio
async def test_permanent_failure_is_terminal() -> None:
    use_case, dao = _use_case(_activation())

    await use_case._record_activation_error(
        uuid4(),
        _PermanentActivationError("invalid reservation"),
    )

    call = dao.record_activation_failure.await_args.kwargs
    assert call["status"] == PromocodeActivationStatus.FAILED
    assert call["next_retry_at"] is None


@pytest.mark.asyncio
async def test_duration_reward_updates_only_expiration_in_remnawave() -> None:
    remna_id = uuid4()
    expire_at = datetime(2030, 9, 27, tzinfo=UTC)
    subscription = SimpleNamespace(
        user_remna_id=remna_id,
        expire_at=expire_at,
        status=SubscriptionStatus.ACTIVE,
        url="old-url",
    )
    remna_user = SimpleNamespace(
        status=SubscriptionStatus.ACTIVE.value,
        expire_at=expire_at,
        subscription_url="new-url",
    )
    remnawave = SimpleNamespace(
        update_user_expire_at=AsyncMock(return_value=remna_user),
        update_user_subscription=AsyncMock(),
        update_user_traffic_limit=AsyncMock(),
        update_user_device_limit=AsyncMock(),
    )
    subscription_dao = SimpleNamespace(
        get_by_remna_id=AsyncMock(return_value=subscription),
        update=AsyncMock(),
    )
    use_case = ActivatePromocode.__new__(ActivatePromocode)
    use_case.remnawave = remnawave
    use_case.subscription_dao = subscription_dao
    activation = SimpleNamespace(
        target_remna_id=remna_id,
        remote_action=PromocodeRemoteAction.UPDATE_SUBSCRIPTION,
        reward_type_snapshot=PromocodeRewardType.DURATION,
        reset_traffic=False,
    )

    await use_case._apply_remote_action(SimpleNamespace(), activation)

    remnawave.update_user_expire_at.assert_awaited_once_with(remna_id, expire_at)
    remnawave.update_user_subscription.assert_not_awaited()
    remnawave.update_user_traffic_limit.assert_not_awaited()
    remnawave.update_user_device_limit.assert_not_awaited()
    subscription_dao.update.assert_awaited_once_with(subscription)


def test_expired_duration_reward_starts_from_activation_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2030, 9, 27, 12, tzinfo=UTC)
    expired_at = datetime(2030, 9, 20, 12, tzinfo=UTC)
    subscription = SimpleNamespace(expire_at=expired_at)
    promo = SimpleNamespace(reward=1)
    monkeypatch.setattr(
        "src.application.use_cases.promocode.commands.activate.datetime_now",
        lambda: now,
    )

    reward = ActivatePromocode._prepare_duration(promo, subscription)

    assert subscription.expire_at == datetime(2030, 9, 28, 12, tzinfo=UTC)
    assert reward.subscription_update is subscription


def test_active_duration_reward_extends_existing_expiration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2030, 9, 27, 12, tzinfo=UTC)
    active_until = datetime(2030, 10, 20, 12, tzinfo=UTC)
    subscription = SimpleNamespace(expire_at=active_until)
    promo = SimpleNamespace(reward=1)
    monkeypatch.setattr(
        "src.application.use_cases.promocode.commands.activate.datetime_now",
        lambda: now,
    )

    ActivatePromocode._prepare_duration(promo, subscription)

    assert subscription.expire_at == datetime(2030, 10, 21, 12, tzinfo=UTC)


def test_duration_reward_accepts_expired_but_not_disabled_subscription() -> None:
    expired = SimpleNamespace(status=SubscriptionStatus.EXPIRED, is_active=False)
    disabled = SimpleNamespace(status=SubscriptionStatus.DISABLED, is_active=False)

    assert ValidatePromocode._can_apply_to_subscription(
        PromocodeRewardType.DURATION,
        expired,
    )
    assert not ValidatePromocode._can_apply_to_subscription(
        PromocodeRewardType.DURATION,
        disabled,
    )
