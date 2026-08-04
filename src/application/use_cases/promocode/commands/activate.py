from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Optional
from uuid import UUID, uuid4

from adaptix import Retort
from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import PromocodeDao, SubscriptionDao, UserDao
from src.application.common.policy import Permission
from src.application.common.remnawave import Remnawave
from src.application.common.uow import UnitOfWork
from src.application.dto import PlanSnapshotDto, PromocodeDto, SubscriptionDto, UserDto
from src.application.dto.promocode import PromocodeActivationDto
from src.application.use_cases.promocode.queries.validate import (
    ValidatePromocode,
    ValidatePromocodeDto,
)
from src.core.enums import (
    PromocodeActivationEventStatus,
    PromocodeActivationStatus,
    PromocodeRemoteAction,
    PromocodeRewardType,
    SubscriptionStatus,
)
from src.core.exceptions import (
    PromocodeIdempotencyConflictError,
    PromocodeNotAvailableError,
    PromocodeNotFoundError,
)
from src.core.utils.converters import days_to_datetime
from src.core.utils.time import datetime_now

PROMOCODE_ACTIVATION_MAX_ATTEMPTS = 8
PROMOCODE_RETRY_DELAYS_SECONDS = (60, 120, 300, 900, 1800, 3600, 7200, 21600)


class _ActivationDeferredError(Exception):
    pass


class _PermanentActivationError(RuntimeError):
    pass


def get_promocode_retry_delay(attempt_count: int) -> timedelta:
    index = min(max(attempt_count, 1), len(PROMOCODE_RETRY_DELAYS_SECONDS)) - 1
    return timedelta(seconds=PROMOCODE_RETRY_DELAYS_SECONDS[index])


@dataclass(frozen=True)
class ActivatePromocodeDto:
    code: str
    user: UserDto
    request_id: Optional[UUID] = None


@dataclass(frozen=True)
class _PendingReward:
    subscription_update: Optional[SubscriptionDto] = None
    subscription_create: Optional[SubscriptionDto] = None
    user_update: Optional[UserDto] = None
    remote_action: PromocodeRemoteAction = PromocodeRemoteAction.NONE
    reset_traffic: bool = False

    @property
    def target_remna_id(self) -> Optional[UUID]:
        subscription = self.subscription_update or self.subscription_create
        return subscription.user_remna_id if subscription is not None else None


class ActivatePromocode(Interactor[ActivatePromocodeDto, PromocodeDto]):
    required_permission = Permission.PUBLIC

    def __init__(
        self,
        uow: UnitOfWork,
        promocode_dao: PromocodeDao,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        remnawave: Remnawave,
        validate_promocode: ValidatePromocode,
        retort: Retort,
    ) -> None:
        self.uow = uow
        self.promocode_dao = promocode_dao
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave
        self.validate_promocode = validate_promocode
        self.retort = retort

    async def _execute(self, actor: UserDto, data: ActivatePromocodeDto) -> PromocodeDto:
        request_id = data.request_id or uuid4()
        activation = await self.promocode_dao.get_activation_by_request_id(request_id)

        if activation is None:
            activation, promo = await self._reserve_activation(
                actor,
                data,
                request_id,
            )
        else:
            promo = await self._get_matching_promo(activation, data)

        if activation.status == PromocodeActivationStatus.APPLIED:
            return promo
        if activation.status == PromocodeActivationStatus.FAILED:
            raise PromocodeNotAvailableError("Promocode activation failed")
        if activation.status == PromocodeActivationStatus.REQUIRES_REVIEW:
            raise PromocodeNotAvailableError("Promocode activation requires manual review")

        if activation.status == PromocodeActivationStatus.PENDING:
            if activation.next_retry_at and activation.next_retry_at > datetime_now():
                raise PromocodeNotAvailableError("Promocode activation retry is scheduled")
            promo = await self._apply_reserved_activation(
                data.user,
                request_id,
                data.code,
            )

        return promo

    async def _reserve_activation(
        self,
        actor: UserDto,
        data: ActivatePromocodeDto,
        request_id: UUID,
    ) -> tuple[PromocodeActivationDto, PromocodeDto]:
        user = data.user

        async with self.uow:
            await self.promocode_dao.lock_activation_request(request_id)

            existing = await self.promocode_dao.get_activation_by_request_id(request_id)
            if existing is not None:
                promo = await self._get_matching_promo(existing, data)
                await self.uow.rollback()
                return existing, promo

            locked_promo = await self.promocode_dao.get_by_code_for_update(data.code)
            if locked_promo is None:
                raise PromocodeNotFoundError("Promocode not found")

            await self.promocode_dao.lock_activation_user(user.id)

            pending = await self.promocode_dao.get_pending_activation_by_user(user.id)
            if pending is not None:
                raise PromocodeNotAvailableError(
                    "Another promocode activation is pending or requires review"
                )

            promo = await self.validate_promocode(
                actor,
                ValidatePromocodeDto(code=data.code, user=user),
            )
            subscription = await self.subscription_dao.get_current(user.id)
            reward = self._prepare_reward(user, promo, subscription)
            status = (
                PromocodeActivationStatus.APPLIED
                if reward.remote_action == PromocodeRemoteAction.NONE
                else PromocodeActivationStatus.PENDING
            )

            assert promo.id is not None
            activation = await self.promocode_dao.create_activation(
                PromocodeActivationDto(
                    promocode_id=promo.id,
                    user_id=user.id,
                    activated_at=datetime_now(),
                    code_snapshot=promo.code,
                    reward_type_snapshot=promo.reward_type,
                    reward_snapshot=promo.reward,
                    plan_snapshot=promo.plan_snapshot,
                    request_id=request_id,
                    status=status,
                    remote_action=reward.remote_action,
                    target_remna_id=reward.target_remna_id,
                    reset_traffic=reward.reset_traffic,
                    event_status=(
                        PromocodeActivationEventStatus.PENDING
                        if status == PromocodeActivationStatus.APPLIED
                        else None
                    ),
                ),
                max_activations=promo.max_activations,
                is_reusable=promo.is_reusable,
            )
            await self._persist_reward(user, reward)
            await self.uow.commit()

        return activation, self._promo_from_snapshot(activation, promo)

    async def _get_matching_promo(
        self,
        activation: PromocodeActivationDto,
        data: ActivatePromocodeDto,
    ) -> PromocodeDto:
        promo = await self.promocode_dao.get_by_id(activation.promocode_id)
        normalized_code = data.code.strip().upper()
        if (
            promo is None
            or activation.user_id != data.user.id
            or activation.code_snapshot.upper() != normalized_code
        ):
            raise PromocodeIdempotencyConflictError(
                "request_id was already used for another promocode activation"
            )
        return self._promo_from_snapshot(activation, promo)

    @staticmethod
    def _promo_from_snapshot(
        activation: PromocodeActivationDto,
        promo: PromocodeDto,
    ) -> PromocodeDto:
        return replace(
            promo,
            code=activation.code_snapshot,
            reward_type=activation.reward_type_snapshot,
            reward=activation.reward_snapshot,
            plan_snapshot=activation.plan_snapshot,
        )

    async def _apply_reserved_activation(
        self,
        user: UserDto,
        request_id: UUID,
        code: str,
    ) -> PromocodeDto:
        try:
            async with self.uow:
                activation = await self.promocode_dao.get_activation_by_request_id(
                    request_id,
                    for_update=True,
                )
                if activation is None:
                    raise RuntimeError(f"Promocode activation request '{request_id}' not found")

                promo = await self._get_matching_promo(
                    activation,
                    ActivatePromocodeDto(code=code, user=user, request_id=request_id),
                )
                if activation.status == PromocodeActivationStatus.APPLIED:
                    await self.uow.rollback()
                    return promo
                if activation.status != PromocodeActivationStatus.PENDING:
                    raise _ActivationDeferredError(
                        f"Promocode activation is in terminal state '{activation.status}'"
                    )
                if activation.next_retry_at and activation.next_retry_at > datetime_now():
                    raise _ActivationDeferredError("Promocode activation retry is scheduled")

                persisted_user = await self.user_dao.get_by_id(user.id)
                if persisted_user is None:
                    raise _PermanentActivationError(f"User '{user.id}' not found")

                await self._apply_remote_action(persisted_user, activation)
                await self.promocode_dao.mark_activation_applied(request_id)
                await self.uow.commit()
                return promo
        except _ActivationDeferredError as error:
            raise PromocodeNotAvailableError(str(error)) from error
        except Exception as error:
            await self._record_activation_error(request_id, error)
            raise

    async def _apply_remote_action(
        self,
        user: UserDto,
        activation: PromocodeActivationDto,
    ) -> None:
        target_remna_id = activation.target_remna_id
        if target_remna_id is None:
            raise _PermanentActivationError(
                "Promocode activation has no target Remnawave user"
            )

        subscription = await self.subscription_dao.get_by_remna_id(target_remna_id)
        if subscription is None:
            raise _PermanentActivationError(
                f"Subscription for Remnawave user '{target_remna_id}' not found"
            )

        if activation.remote_action == PromocodeRemoteAction.UPDATE_SUBSCRIPTION:
            remna_user = await self.remnawave.update_user(
                user=user,
                uuid=target_remna_id,
                subscription=subscription,
                reset_traffic=activation.reset_traffic,
            )
        elif activation.remote_action == PromocodeRemoteAction.CREATE_SUBSCRIPTION:
            remna_user = await self.remnawave.get_user_by_uuid(target_remna_id)
            if remna_user is None:
                remna_user = await self.remnawave.create_user(
                    user=user,
                    subscription=subscription,
                )
        else:
            return

        subscription.status = SubscriptionStatus(remna_user.status)
        subscription.expire_at = remna_user.expire_at
        subscription.url = remna_user.subscription_url
        await self.subscription_dao.update(subscription)

    async def _record_activation_error(self, request_id: UUID, error: Exception) -> None:
        try:
            async with self.uow:
                activation = await self.promocode_dao.get_activation_by_request_id(
                    request_id,
                    for_update=True,
                )
                if (
                    activation is None
                    or activation.status != PromocodeActivationStatus.PENDING
                ):
                    await self.uow.rollback()
                    return

                attempt_count = activation.attempt_count + 1
                if isinstance(error, _PermanentActivationError):
                    status = PromocodeActivationStatus.FAILED
                    next_retry_at = None
                elif activation.reset_traffic:
                    status = PromocodeActivationStatus.REQUIRES_REVIEW
                    next_retry_at = None
                elif attempt_count >= PROMOCODE_ACTIVATION_MAX_ATTEMPTS:
                    status = PromocodeActivationStatus.REQUIRES_REVIEW
                    next_retry_at = None
                else:
                    status = PromocodeActivationStatus.PENDING
                    next_retry_at = datetime_now() + get_promocode_retry_delay(attempt_count)

                await self.promocode_dao.record_activation_failure(
                    request_id=request_id,
                    error=str(error),
                    status=status,
                    attempt_count=attempt_count,
                    next_retry_at=next_retry_at,
                )
                await self.uow.commit()
                logger.warning(
                    f"Promocode activation '{request_id}' failed on attempt "
                    f"'{attempt_count}', status set to '{status}'"
                )
        except Exception:
            logger.exception(
                f"Failed to persist error for promocode activation request '{request_id}'"
            )

    def _prepare_reward(
        self,
        user: UserDto,
        promo: PromocodeDto,
        subscription: Optional[SubscriptionDto],
    ) -> _PendingReward:
        match promo.reward_type:
            case PromocodeRewardType.DURATION:
                return self._prepare_duration(promo, subscription)
            case PromocodeRewardType.TRAFFIC:
                return self._prepare_traffic(promo, subscription)
            case PromocodeRewardType.DEVICES:
                return self._prepare_devices(promo, subscription)
            case PromocodeRewardType.SUBSCRIPTION:
                return self._prepare_subscription(promo, subscription)
            case PromocodeRewardType.PERSONAL_DISCOUNT:
                return self._prepare_personal_discount(user, promo)
            case PromocodeRewardType.PURCHASE_DISCOUNT:
                return self._prepare_purchase_discount(user, promo)
        raise ValueError(f"Unsupported promocode reward type '{promo.reward_type}'")

    @staticmethod
    def _prepare_duration(
        promo: PromocodeDto,
        subscription: Optional[SubscriptionDto],
    ) -> _PendingReward:
        if subscription is None or promo.reward is None:
            return _PendingReward()
        subscription.expire_at = (
            days_to_datetime(0)
            if promo.reward == 0
            else subscription.expire_at + timedelta(days=promo.reward)
        )
        return _PendingReward(
            subscription_update=subscription,
            remote_action=PromocodeRemoteAction.UPDATE_SUBSCRIPTION,
        )

    @staticmethod
    def _prepare_traffic(
        promo: PromocodeDto,
        subscription: Optional[SubscriptionDto],
    ) -> _PendingReward:
        if subscription is None or promo.reward is None:
            return _PendingReward()
        subscription.traffic_limit = (
            0 if promo.reward == 0 else subscription.traffic_limit + promo.reward
        )
        return _PendingReward(
            subscription_update=subscription,
            remote_action=PromocodeRemoteAction.UPDATE_SUBSCRIPTION,
        )

    @staticmethod
    def _prepare_devices(
        promo: PromocodeDto,
        subscription: Optional[SubscriptionDto],
    ) -> _PendingReward:
        if subscription is None or promo.reward is None:
            return _PendingReward()
        subscription.device_limit = (
            0 if promo.reward == 0 else subscription.device_limit + promo.reward
        )
        return _PendingReward(
            subscription_update=subscription,
            remote_action=PromocodeRemoteAction.UPDATE_SUBSCRIPTION,
        )

    def _prepare_subscription(
        self,
        promo: PromocodeDto,
        subscription: Optional[SubscriptionDto],
    ) -> _PendingReward:
        if not promo.plan_snapshot:
            return _PendingReward()

        plan = self.retort.load(promo.plan_snapshot, PlanSnapshotDto)
        if subscription is not None:
            subscription.status = SubscriptionStatus.ACTIVE
            subscription.traffic_limit = plan.traffic_limit
            subscription.device_limit = plan.device_limit
            subscription.traffic_limit_strategy = plan.traffic_limit_strategy
            subscription.tag = plan.tag
            subscription.internal_squads = plan.internal_squads
            subscription.external_squad = plan.external_squad
            subscription.expire_at = days_to_datetime(plan.duration)
            subscription.plan_snapshot = plan
            return _PendingReward(
                subscription_update=subscription,
                remote_action=PromocodeRemoteAction.UPDATE_SUBSCRIPTION,
                reset_traffic=True,
            )

        new_subscription = SubscriptionDto(
            user_remna_id=uuid4(),
            status=SubscriptionStatus.ACTIVE,
            is_trial=False,
            traffic_limit=plan.traffic_limit,
            device_limit=plan.device_limit,
            traffic_limit_strategy=plan.traffic_limit_strategy,
            tag=plan.tag,
            internal_squads=plan.internal_squads,
            external_squad=plan.external_squad,
            expire_at=days_to_datetime(plan.duration),
            url="",
            plan_snapshot=plan,
        )
        return _PendingReward(
            subscription_create=new_subscription,
            remote_action=PromocodeRemoteAction.CREATE_SUBSCRIPTION,
        )

    @staticmethod
    def _prepare_personal_discount(user: UserDto, promo: PromocodeDto) -> _PendingReward:
        if promo.reward:
            user.personal_discount = promo.reward
            return _PendingReward(user_update=user)
        return _PendingReward()

    @staticmethod
    def _prepare_purchase_discount(user: UserDto, promo: PromocodeDto) -> _PendingReward:
        if promo.reward:
            user.purchase_discount = promo.reward
            return _PendingReward(user_update=user)
        return _PendingReward()

    async def _persist_reward(self, user: UserDto, reward: _PendingReward) -> None:
        if reward.subscription_update is not None:
            await self.subscription_dao.update(reward.subscription_update)
        if reward.subscription_create is not None:
            await self.subscription_dao.create(
                subscription=reward.subscription_create,
                user_id=user.id,
            )
        if reward.user_update is not None:
            await self.user_dao.update(reward.user_update)
