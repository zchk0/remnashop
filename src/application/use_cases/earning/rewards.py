from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from adaptix import Retort, dumper
from aiogram.enums import ChatMemberStatus
from loguru import logger

from src.application.common import BotService, EventPublisher, Interactor, Remnawave
from src.application.common.dao import PlanDao, SettingsDao, SubscriptionDao, UserDao
from src.application.common.dao.earning import EarningDao
from src.application.common.policy import Permission
from src.application.common.uow import UnitOfWork
from src.application.dto import PlanSnapshotDto, SubscriptionDto, UserDto
from src.application.dto.earning import ChannelClaimDto, ChannelTaskDto
from src.application.events import EarningTaskCompletedEvent
from src.core.enums import SubscriptionStatus
from src.core.types import RemnaUserDto
from src.core.utils.panel_identity import subscription_ref
from src.core.utils.time import datetime_now


class EarningError(ValueError):
    """A translation key safe to display to the user."""


def _panel_expiration(value: datetime) -> datetime:
    # The panel stores JavaScript dates with millisecond precision.
    return value.replace(microsecond=value.microsecond // 1000 * 1000)


def _review_required(claim: ChannelClaimDto, reason: str, **details: Any) -> EarningError:
    logger.warning(
        "Earning reward requires review: task_id={} user_id={} reason={} "
        "subscription_applied={} reset_started={} reset_applied={} details={}",
        claim.task_id,
        claim.user_id,
        reason,
        claim.subscription_applied,
        claim.reset_started,
        claim.reset_applied,
        details,
    )
    return EarningError("ntf-earning.review-required")


@dataclass(frozen=True)
class EarningTasksDto:
    tasks: list[ChannelTaskDto]
    subscription: SubscriptionDto | None


class GetEarningTasks(Interactor[None, EarningTasksDto]):
    required_permission = Permission.PUBLIC

    def __init__(
        self,
        earning_dao: EarningDao,
        settings_dao: SettingsDao,
        subscription_dao: SubscriptionDao,
    ) -> None:
        self.earning_dao = earning_dao
        self.settings_dao = settings_dao
        self.subscription_dao = subscription_dao

    async def _execute(self, actor: UserDto, data: None) -> EarningTasksDto:
        settings = await self.settings_dao.get()
        subscription = await self.subscription_dao.get_current(actor.id)
        if not settings.earning.allows(actor):
            return EarningTasksDto([], subscription)
        claims = {claim.task_id: claim for claim in await self.earning_dao.get_claims(actor.id)}
        tasks = []
        for task in await self.earning_dao.list_tasks():
            claim = claims.get(task.id)
            if claim:
                if claim.status != "completed":
                    tasks.append(self._pending_task(task, claim))
            elif (
                task.active
                and task.eligible(subscription)
                and (task.max_claims is None or task.claims_count < task.max_claims)
            ):
                tasks.append(task)
        listed_ids = {task.id for task in tasks}
        for claim in claims.values():
            if claim.status != "completed" and claim.task_id not in listed_ids:
                pending_task = await self.earning_dao.get_task(claim.task_id)
                if pending_task:
                    tasks.append(self._pending_task(pending_task, claim))
        return EarningTasksDto(tasks, subscription)

    @staticmethod
    def _pending_task(task: ChannelTaskDto, claim: ChannelClaimDto) -> ChannelTaskDto:
        snapshot = ChannelTaskDto(**claim.payload.get("task_snapshot", asdict(task)))
        return replace(
            snapshot,
            days=claim.payload.get("days", snapshot.days),
            trial_plan_id=None,
            claims_count=task.claims_count,
            max_claims=task.max_claims,
        )


class ClaimChannelReward(Interactor[int, None]):
    required_permission = Permission.PUBLIC

    def __init__(
        self,
        earning_dao: EarningDao,
        settings_dao: SettingsDao,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        plan_dao: PlanDao,
        bot_service: BotService,
        remnawave: Remnawave,
        retort: Retort,
        uow: UnitOfWork,
        event_publisher: EventPublisher,
    ) -> None:
        self.earning_dao = earning_dao
        self.settings_dao = settings_dao
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.plan_dao = plan_dao
        self.bot_service = bot_service
        self.remnawave = remnawave
        self.retort = retort.extend(recipe=[dumper(datetime, datetime.isoformat)])
        self.uow = uow
        self.event_publisher = event_publisher

    async def _execute(self, actor: UserDto, task_id: int) -> None:
        settings = await self.settings_dao.get()
        if not settings.earning.allows(actor):
            raise EarningError("ntf-earning.unavailable")
        await self._reserve(actor, task_id)
        await self.apply_reserved(actor, task_id)

    async def _reserve(self, actor: UserDto, task_id: int) -> None:
        async with self.uow:
            # All reward flows take the user lock first, then the task lock.
            await self.earning_dao.lock_user(actor.id)
            existing = await self.earning_dao.get_claim(task_id, actor.id)
            if existing:
                if existing.status == "completed":
                    raise EarningError("ntf-earning.already-claimed")
                await self.uow.commit()
                return
            pending = await self.earning_dao.get_claims(actor.id)
            if any(claim.status != "completed" for claim in pending):
                raise EarningError("ntf-earning.finish-pending")
            task = await self.earning_dao.get_task(task_id, lock=True)
            if not task or not task.active or task.deleted:
                raise EarningError("ntf-earning.unavailable")
            if task.max_claims is not None and task.claims_count >= task.max_claims:
                raise EarningError("ntf-earning.full")
            subscription = await self.subscription_dao.get_current(actor.id)
            if not task.eligible(subscription):
                raise EarningError("ntf-earning.subscription-required")
            assert actor.telegram_id is not None
            member = await self.bot_service.get_chat_member(task.channel_id, actor.telegram_id)
            if member.status not in (
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.CREATOR,
            ):
                raise EarningError("ntf-earning.not-subscribed")
            payload = await self._prepare(task, subscription)
            await self.earning_dao.save_claim(
                ChannelClaimDto(
                    task_id=task.id,
                    user_id=actor.id,
                    payload=payload,
                )
            )
            # Reserve capacity and immutable reward targets before any panel call.
            await self.uow.commit()

    async def _prepare(
        self,
        task: ChannelTaskDto,
        subscription: SubscriptionDto | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "task_snapshot": asdict(task),
            "discount": task.discount,
            "reset_traffic": task.reset_traffic,
            "old_subscription_id": subscription.id if subscription else None,
            "old_expire_at": subscription.expire_at.isoformat() if subscription else None,
            "subscription_before": (
                self.retort.dump(subscription, SubscriptionDto) if subscription else None
            ),
            "replace": False,
        }
        days = task.reward_days(subscription)
        plan_id = (
            task.plan_id
            if subscription is None
            else (task.trial_plan_id if subscription.is_trial and task.days else None)
        )
        target = subscription
        if plan_id and days:
            plan = await self.plan_dao.get_by_id(plan_id)
            if not plan or plan.is_trial:
                raise EarningError("ntf-earning.plan-unavailable")
            snapshot = PlanSnapshotDto.from_plan(plan, days)
            target = SubscriptionDto(
                user_remna_id=subscription.user_remna_id if subscription else uuid4(),
                panel_user_id=subscription.panel_user_id if subscription else None,
                traffic_limit=plan.traffic_limit,
                device_limit=plan.device_limit,
                traffic_limit_strategy=plan.traffic_limit_strategy,
                tag=plan.tag,
                internal_squads=plan.internal_squads,
                external_squad=plan.external_squad,
                expire_at=datetime_now() + timedelta(days=days),
                url=subscription.url if subscription else "",
                plan_snapshot=snapshot,
            )
            payload["replace"] = True
            payload["short_uuid"] = uuid4().hex[:16]
        elif days and subscription:
            target = replace(
                subscription,
                expire_at=(
                    subscription.expire_at
                    if subscription.is_unlimited
                    else max(datetime_now(), subscription.expire_at) + timedelta(days=days)
                ),
            )
            if subscription.status != SubscriptionStatus.DISABLED:
                target.status = SubscriptionStatus.ACTIVE
        payload["days"] = days
        if target and (task.days or task.reset_traffic):
            if days:
                target.expire_at = _panel_expiration(target.expire_at)
            payload["subscription"] = self.retort.dump(target, SubscriptionDto)
        return payload

    async def apply_reserved(self, actor: UserDto, task_id: int) -> None:
        async with self.uow:
            await self.earning_dao.lock_user(actor.id)
            claim = await self.earning_dao.get_claim(task_id, actor.id)
            assert claim is not None
            if claim.status == "completed":
                raise EarningError("ntf-earning.already-claimed")
            if claim.reset_started and not claim.reset_applied:
                # Telegram callbacks cannot safely replay a reset with a lost panel reply.
                raise _review_required(claim, "traffic_reset_result_unknown")
            payload = claim.payload
            target = (
                self.retort.load(payload["subscription"], SubscriptionDto)
                if ("subscription" in payload)
                else None
            )
            if target and payload["days"]:
                # Older reservations may still contain Python's microseconds.
                target.expire_at = _panel_expiration(target.expire_at)
            if target and not claim.subscription_applied:
                await self._apply_subscription(actor, claim, target)
                payload = claim.payload
            if payload["reset_traffic"] and target:
                await self._apply_traffic_reset(actor, claim, target)
            fresh_user = await self.user_dao.get_by_id(actor.id)
            discount_before = (
                fresh_user.purchase_discount if fresh_user else actor.purchase_discount
            )
            if fresh_user and payload["discount"] > fresh_user.purchase_discount:
                fresh_user.purchase_discount = payload["discount"]
                await self.user_dao.update(fresh_user)
            task = payload["task_snapshot"]
            user = fresh_user or actor
            event = EarningTaskCompletedEvent(
                user_id=user.id,
                telegram_id=user.telegram_id,
                username=user.username,
                email=user.email,
                name=user.name,
                task_id=task_id,
                channel_id=task["channel_id"],
                channel_title=task["title"],
                channel_url=task["channel_url"],
                days=payload["days"],
                reset_traffic=payload["reset_traffic"],
                discount=payload["discount"],
                discount_before=discount_before,
                discount_after=user.purchase_discount,
                subscription_before=(
                    self.retort.load(payload["subscription_before"], SubscriptionDto)
                    if payload.get("subscription_before")
                    else None
                ),
                subscription_after=await self.subscription_dao.get_current(actor.id),
                subscription_before_known="subscription_before" in payload,
                traffic_before=payload.get("traffic_before"),
                traffic_after=payload.get("traffic_after"),
            )
            claim.status = "completed"
            await self.earning_dao.save_claim(claim)
            await self.uow.commit()

        # A notification failure must not turn an already granted reward into an error.
        try:
            await self.event_publisher.publish(event)
        except Exception:
            logger.exception(
                f"Failed to publish completion of earning task '{task_id}' for '{actor.id}'"
            )

    @staticmethod
    def _traffic_used(user: RemnaUserDto | None) -> int | None:
        return user.user_traffic.used_traffic_bytes if user else None

    async def _get_traffic_used(self, subscription: SubscriptionDto) -> int | None:
        try:
            return self._traffic_used(
                await self.remnawave.get_user_by_uuid(subscription_ref(subscription))
            )
        except Exception:
            logger.opt(exception=True).warning(
                f"Could not read traffic before/after earning reward for '{subscription.user_id}'"
            )
            return None

    async def _apply_traffic_reset(
        self, actor: UserDto, claim: ChannelClaimDto, target: SubscriptionDto
    ) -> None:
        payload = claim.payload
        if not claim.reset_applied:
            payload["traffic_before"] = await self._get_traffic_used(target)
            claim.reset_started = True
            await self.earning_dao.save_claim(claim)
            await self.uow.commit()
            await self.earning_dao.lock_user(actor.id)
            current = await self.subscription_dao.get_current(actor.id)
            if not current or current.id != target.id:
                raise _review_required(
                    claim,
                    "subscription_changed_before_reset",
                    expected_id=target.id,
                    current_id=current.id if current else None,
                )
            result = await self.remnawave.reset_traffic(subscription_ref(target))
            if result is None:
                raise _review_required(
                    claim, "panel_user_not_found", panel_user_id=str(subscription_ref(target))
                )
            claim.reset_applied = True
            payload["traffic_after"] = self._traffic_used(result)
        if "traffic_after" not in payload:
            # An administrator can confirm a reset whose response was lost.
            payload["traffic_after"] = await self._get_traffic_used(target)
        current = await self.subscription_dao.get_current(actor.id)
        if current and current.id == target.id and current.status == SubscriptionStatus.LIMITED:
            await self.subscription_dao.update_status(current.id, SubscriptionStatus.ACTIVE)

    async def _apply_subscription(
        self,
        actor: UserDto,
        claim: ChannelClaimDto,
        target: SubscriptionDto,
    ) -> None:
        payload = claim.payload
        current = await self.subscription_dao.get_current(actor.id)
        if (current.id if current else None) != payload["old_subscription_id"]:
            raise _review_required(
                claim,
                "subscription_changed",
                expected_id=payload["old_subscription_id"],
                current_id=current.id if current else None,
            )
        if (
            payload["days"]
            and current
            and _panel_expiration(current.expire_at)
            not in (
                _panel_expiration(datetime.fromisoformat(payload["old_expire_at"])),
                _panel_expiration(target.expire_at),
            )
        ):
            raise _review_required(
                claim,
                "subscription_expiration_changed",
                original_expire_at=payload["old_expire_at"],
                target_expire_at=target.expire_at.isoformat(),
                current_expire_at=current.expire_at.isoformat(),
            )
        if payload["replace"]:
            if current:
                remote = await self.remnawave.update_user_subscription(
                    uuid=subscription_ref(current),
                    subscription=target,
                )
                await self.subscription_dao.update_status(current.id, SubscriptionStatus.DELETED)
            else:
                existing_remote = await self.remnawave.get_user_by_short_uuid(payload["short_uuid"])
                if existing_remote is None:
                    existing_remote = await self.remnawave.create_user(
                        user=actor,
                        subscription=target,
                        short_uuid=payload["short_uuid"],
                    )
                remote = existing_remote
            target.user_remna_id = remote.uuid
            target.panel_user_id = remote.id
            target.url = remote.subscription_url
            created = await self.subscription_dao.create(target, actor.id)
            target.id = created.id
            await self.user_dao.set_trial_available(actor.id, False)
        elif payload["days"] and current:
            # Absolute expiration makes retrying a lost response idempotent.
            was_expired = current.is_expired
            remote = await self.remnawave.update_user_expire_at(
                subscription_ref(current), target.expire_at
            )
            current.expire_at = target.expire_at
            if was_expired and current.status in (
                SubscriptionStatus.ACTIVE,
                SubscriptionStatus.EXPIRED,
            ):
                # Extending an expired account can activate it in the panel already.
                current.status = SubscriptionStatus(remote.status)
                if current.status == SubscriptionStatus.EXPIRED:
                    await self.remnawave.enable_user(subscription_ref(current))
                    current.status = SubscriptionStatus.ACTIVE
            await self.subscription_dao.update(current)
        claim.subscription_applied = True
        claim.payload = {**payload, "subscription": self.retort.dump(target, SubscriptionDto)}
        await self.earning_dao.save_claim(claim)


@dataclass(frozen=True)
class ResolveEarningClaimDto:
    task_id: int
    user_id: int
    confirm_reset: bool = False


class ResolveEarningClaim(Interactor[ResolveEarningClaimDto, None]):
    required_permission = Permission.MANAGE_EARNING

    def __init__(
        self,
        earning_dao: EarningDao,
        user_dao: UserDao,
        uow: UnitOfWork,
        claim_reward: ClaimChannelReward,
    ) -> None:
        self.earning_dao = earning_dao
        self.user_dao = user_dao
        self.uow = uow
        self.claim_reward = claim_reward

    async def _execute(self, actor: UserDto, data: ResolveEarningClaimDto) -> None:
        async with self.uow:
            await self.earning_dao.lock_user(data.user_id)
            claim = await self.earning_dao.get_claim(data.task_id, data.user_id)
            if not claim or claim.status == "completed":
                raise EarningError("ntf-earning.already-claimed")
            if data.confirm_reset:
                if not claim.reset_started or claim.reset_applied:
                    raise EarningError("ntf-earning.unavailable")
                claim.reset_applied = True
                await self.earning_dao.save_claim(claim)
            user = await self.user_dao.get_by_id(data.user_id)
            if not user:
                raise EarningError("ntf-earning.unavailable")
            await self.uow.commit()
        await self.claim_reward.apply_reserved(user, data.task_id)
