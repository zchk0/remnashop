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
from src.core.enums import PromocodeActivationStatus


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
