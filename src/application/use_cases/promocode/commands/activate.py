from dataclasses import dataclass
from datetime import timedelta
from typing import Optional
from uuid import UUID, uuid4

from adaptix import Retort
from loguru import logger

from src.application.common import EventPublisher, Interactor
from src.application.common.dao import PromocodeDao, SubscriptionDao, UserDao
from src.application.common.policy import Permission
from src.application.common.remnawave import Remnawave
from src.application.common.uow import UnitOfWork
from src.application.dto import PlanSnapshotDto, PromocodeDto, SubscriptionDto, UserDto
from src.application.dto.promocode import PromocodeActivationDto
from src.application.events.system import PromocodeActivatedEvent
from src.application.use_cases.promocode.queries.validate import (
    ValidatePromocode,
    ValidatePromocodeDto,
)
from src.core.enums import (
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
        event_publisher: EventPublisher,
        retort: Retort,
    ) -> None:
        self.uow = uow
        self.promocode_dao = promocode_dao
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave
        self.validate_promocode = validate_promocode
        self.event_publisher = event_publisher
        self.retort = retort

    async def _execute(self, actor: UserDto, data: ActivatePromocodeDto) -> PromocodeDto:
        request_id = data.request_id or uuid4()
        activation = await self.promocode_dao.get_activation_by_request_id(request_id)

        if activation is None:
            activation, promo, newly_applied = await self._reserve_activation(
                actor,
                data,
                request_id,
            )
        else:
            promo = await self._get_matching_promo(activation, data)
            newly_applied = False

        if activation.status == PromocodeActivationStatus.PENDING:
            promo, newly_applied = await self._apply_reserved_activation(
                data.user,
                request_id,
                data.code,
            )

        if newly_applied:
            await self._publish_activation_event(data.user, promo)

        return promo

    async def _reserve_activation(
        self,
        actor: UserDto,
        data: ActivatePromocodeDto,
        request_id: UUID,
    ) -> tuple[PromocodeActivationDto, PromocodeDto, bool]:
        user = data.user

        async with self.uow:
            await self.promocode_dao.lock_activation_request(request_id)

            existing = await self.promocode_dao.get_activation_by_request_id(request_id)
            if existing is not None:
                promo = await self._get_matching_promo(existing, data)
                await self.uow.rollback()
                return existing, promo, False

            locked_promo = await self.promocode_dao.get_by_code_for_update(data.code)
            if locked_promo is None:
                raise PromocodeNotFoundError("Promocode not found")

            await self.promocode_dao.lock_activation_user(user.id)

            pending = await self.promocode_dao.get_pending_activation_by_user(user.id)
            if pending is not None:
                raise PromocodeNotAvailableError("Another promocode activation is in progress")

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
                    request_id=request_id,
                    status=status,
                    remote_action=reward.remote_action,
                    target_remna_id=reward.target_remna_id,
                    reset_traffic=reward.reset_traffic,
                ),
                max_activations=promo.max_activations,
                is_reusable=promo.is_reusable,
            )
            await self._persist_reward(user, reward)
            await self.uow.commit()

        return activation, promo, status == PromocodeActivationStatus.APPLIED

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
            or promo.code.upper() != normalized_code
        ):
            raise PromocodeIdempotencyConflictError(
                "request_id was already used for another promocode activation"
            )
        return promo

    async def _apply_reserved_activation(
        self,
        user: UserDto,
        request_id: UUID,
        code: str,
    ) -> tuple[PromocodeDto, bool]:
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
                    return promo, False

                persisted_user = await self.user_dao.get_by_id(user.id)
                if persisted_user is None:
                    raise RuntimeError(f"User '{user.id}' not found")

                await self._apply_remote_action(persisted_user, activation)
                await self.promocode_dao.mark_activation_applied(request_id)
                await self.uow.commit()
                return promo, True
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
            raise RuntimeError("Promocode activation has no target Remnawave user")

        subscription = await self.subscription_dao.get_by_remna_id(target_remna_id)
        if subscription is None:
            raise RuntimeError(
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
                await self.promocode_dao.set_activation_error(request_id, str(error))
                await self.uow.commit()
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

    async def _publish_activation_event(self, user: UserDto, promo: PromocodeDto) -> None:
        logger.info(f"{user.log} Activated promocode '{promo.code}'")
        event = PromocodeActivatedEvent(
            user_id=user.id,
            telegram_id=user.telegram_id,
            username=user.username,
            name=user.name,
            promocode_code=promo.code,
            reward_type=promo.reward_type.value,
            reward=promo.reward,
            plan_name=(str(promo.plan_snapshot.get("name")), {})
            if promo.plan_snapshot and promo.plan_snapshot.get("name")
            else "",
        )
        await self.event_publisher.publish(event)
