import hashlib
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import orjson
from adaptix import Retort
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.common import Notifier, Remnawave
from src.application.common.dao import PaymentGatewayDao, SubscriptionDao, TransactionDao, UserDao
from src.application.dto import (
    MessagePayloadDto,
    PlanSnapshotDto,
    PriceDetailsDto,
    SubscriptionDto,
    TransactionDto,
    UserDto,
)
from src.application.dto.payment_gateway import PlategaGatewaySettingsDto
from src.application.use_cases.referral.commands.rewards import (
    AssignReferralRewards,
    AssignReferralRewardsDto,
)
from src.core.enums import (
    Currency,
    PaymentGatewayType,
    PurchaseType,
    SubscriptionStatus,
    TransactionStatus,
)
from src.core.exceptions import AutopayDisabledError
from src.core.utils.panel_identity import subscription_ref
from src.core.utils.time import datetime_now
from src.core.utils.validators import is_valid_email
from src.infrastructure.database.models import RecurringPayment, RecurringPaymentEvent
from src.infrastructure.payment_gateways import PaymentGatewayFactory, PlategaGateway

OPEN_STATUSES = ("Pending", "Active", "PastDue")


class PlategaAutopayService:
    """Manage consent separately from charges; persist targets before touching the panel."""

    def __init__(
        self,
        session: AsyncSession,
        retort: Retort,
        redis: Redis,
        gateway_dao: PaymentGatewayDao,
        subscription_dao: SubscriptionDao,
        transaction_dao: TransactionDao,
        user_dao: UserDao,
        gateway_factory: PaymentGatewayFactory,
        remnawave: Remnawave,
        notifier: Notifier,
        assign_referral_rewards: AssignReferralRewards,
    ) -> None:
        self.session = session
        self.retort = retort
        self.redis = redis
        self.gateway_dao = gateway_dao
        self.subscription_dao = subscription_dao
        self.transaction_dao = transaction_dao
        self.user_dao = user_dao
        self.gateway_factory = gateway_factory
        self.remnawave = remnawave
        self.notifier = notifier
        self.assign_referral_rewards = assign_referral_rewards

    async def gateway(self, *, for_creation: bool = False) -> PlategaGateway:
        data = await self.gateway_dao.get_by_type(PaymentGatewayType.PLATEGA)
        if not data or not isinstance(data.settings, PlategaGatewaySettingsDto):
            raise ValueError("Platega is not configured")
        if not data.settings.is_configured:
            raise ValueError("Platega is not configured")
        if for_creation and not data.is_active:
            raise AutopayDisabledError("Platega gateway is inactive (is_active=False)")
        if for_creation and not data.settings.autopay_enabled:
            raise AutopayDisabledError("Platega autopay is disabled (autopay_enabled=False)")
        return cast(PlategaGateway, self.gateway_factory(data))

    async def current(self, user_id: int) -> RecurringPayment | None:
        result = await self.session.scalar(
            select(RecurringPayment)
            .where(RecurringPayment.user_id == user_id)
            .order_by(RecurringPayment.created_at.desc(), RecurringPayment.id.desc())
            .limit(1)
        )
        return cast(RecurringPayment | None, result)

    async def email(self, user: UserDto, supplied: str | None = None) -> str | None:
        subscription = await self.subscription_dao.get_current(user.id)
        panel_user = (
            await self.remnawave.get_user_by_uuid(subscription_ref(subscription))
            if subscription
            else None
        )
        previous = await self.current(user.id)
        value = supplied or (panel_user.email if panel_user else None)
        value = value or user.billing_email or (previous.email if previous else None) or user.email
        if not value:
            return None
        value = value.strip()
        if len(value) > 255 or not is_valid_email(value):
            raise ValueError("Invalid email")
        if panel_user and panel_user.email != value:
            await self.remnawave.update_user_email(subscription_ref(subscription), value)
        # Billing email never changes login credentials or verifies the address.
        return value

    async def save_email(self, user: UserDto, supplied: str) -> None:
        email = await self.email(user, supplied)
        user.billing_email = email
        await self.user_dao.update(user)
        payment = await self.current(user.id)
        if payment:
            payment.email = email
        await self.session.commit()

    async def refresh(self, payment: RecurringPayment) -> RecurringPayment:
        remote = await (await self.gateway()).get_subscription(payment.id)
        status = str(remote["status"]).replace("_", "").lower()
        statuses = {
            "pending": "Pending",
            "pendingagreement": "Pending",
            "active": "Active",
            "pastdue": "PastDue",
            "cancelled": "Cancelled",
            "canceled": "Cancelled",
            "failed": "Failed",
        }
        if status not in statuses:
            raise ValueError(f"Unknown Platega subscription status: {status}")
        payment.status = statuses[status]
        payment.next_charge_at = self._datetime(remote.get("nextChargeAt"))
        await self.session.commit()
        return payment

    async def create(
        self,
        user: UserDto,
        plan: PlanSnapshotDto,
        pricing: PriceDetailsDto,
        purchase_type: PurchaseType,
        email: str | None = None,
    ) -> RecurringPayment:
        if plan.is_trial:
            raise ValueError("Trial subscriptions do not support autopay")
        gateway = await self.gateway(for_creation=True)
        gateway.subscription_interval(plan.duration)
        if (
            pricing.final_amount <= 0
            or pricing.final_amount != pricing.final_amount.to_integral_value()
        ):
            raise ValueError("Unsupported recurring amount")
        async with self.redis.lock(f"platega-autopay:{user.id}", timeout=300, blocking_timeout=5):
            existing = await self.current(user.id)
            if existing and existing.status in OPEN_STATUSES:
                await self.refresh(existing)
                if existing.status in OPEN_STATUSES:
                    if (
                        existing.status == "Pending"
                        and existing.plan_snapshot == self.retort.dump(plan)
                        and existing.pricing == self.retort.dump(pricing)
                    ):
                        return existing
                    raise ValueError("Disable the existing autopay before creating another")
            try:
                saved_email = await self.email(user, email)
            except Exception:
                logger.exception("Could not read optional email; connecting autopay without it")
                saved_email = None
            result = await gateway.create_subscription(
                pricing.final_amount, f"{plan.name}: {plan.duration} дней", plan.duration
            )
            payment = RecurringPayment(
                id=result.id,
                user_id=user.id,
                status="Pending",
                email=saved_email,
                payment_url=result.url,
                plan_snapshot=self.retort.dump(plan),
                pricing=self.retort.dump(pricing),
                purchase_type=purchase_type.value,
                display_name=gateway.settings.autopay_display_name,
                next_charge_at=None,
            )
            self.session.add(payment)
            await self.session.commit()
            return payment

    async def cancel_for_user(self, user_id: int) -> None:
        async with self.redis.lock(f"platega-autopay:{user_id}", timeout=300, blocking_timeout=5):
            payments = (
                await self.session.scalars(
                    select(RecurringPayment).where(
                        RecurringPayment.user_id == user_id,
                        RecurringPayment.status.in_(OPEN_STATUSES),
                    )
                )
            ).all()
            if not payments:
                return
            gateway = await self.gateway()
            for payment in payments:
                await gateway.cancel_subscription(payment.id)
                payment.status = "Cancelled"
                payment.next_charge_at = None
            await self.session.commit()

    async def receive(self, payload: dict[str, Any]) -> str:
        subscription_id = UUID(payload["subscriptionId"])
        status = str(payload["status"]).upper()
        if status.startswith("SUBSCRIPTION_"):
            identity = f"{subscription_id}:{status}:{payload.get('nextChargeAt')}"
        else:
            identity = f"{UUID(payload['id'])}:{status}"
        event_id = hashlib.sha256(identity.encode()).hexdigest()
        await self.session.execute(
            insert(RecurringPaymentEvent)
            .values(id=event_id, subscription_id=subscription_id, payload=payload, attempts=0)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await self.session.commit()
        return event_id

    async def process(self, event_id: str) -> None:
        event = await self.session.get(RecurringPaymentEvent, event_id)
        if not event or event.processed_at:
            return
        try:
            payment = await self.session.get(RecurringPayment, event.subscription_id)
            if not payment:
                # A callback may beat the response to the create request; retry after persistence.
                raise ValueError(f"Unknown Platega subscription {event.subscription_id}")
            async with self.redis.lock(
                f"platega-autopay:{payment.user_id}", timeout=300, blocking_timeout=5
            ):
                await self.session.refresh(event)
                if event.processed_at:
                    return
                await self._check_pending_target(event, payment.user_id)
                await self._process(event, payment)
        except Exception as error:
            await self.session.rollback()
            event = await self.session.get(RecurringPaymentEvent, event_id)
            if event:
                event.attempts += 1
                event.error = str(error)[:2000]
                await self.session.commit()
            raise

    async def _check_pending_target(self, event: RecurringPaymentEvent, user_id: int) -> None:
        if event.payload["status"] != "CONFIRMED":
            return
        pending = await self.session.scalar(
            select(RecurringPaymentEvent.id)
            .join(RecurringPayment, RecurringPayment.id == RecurringPaymentEvent.subscription_id)
            .where(
                RecurringPayment.user_id == user_id,
                RecurringPaymentEvent.id != event.id,
                RecurringPaymentEvent.processed_at.is_(None),
                RecurringPaymentEvent.target["subscription"].is_not(None),
            )
            .limit(1)
        )
        if pending:
            raise ValueError("An earlier paid entitlement is still being applied")

    async def _process(self, event: RecurringPaymentEvent, payment: RecurringPayment) -> None:  # noqa: C901
        data = event.payload
        status = str(data["status"]).upper()
        if status.startswith("SUBSCRIPTION_"):
            # Read authoritative state so delayed activation callbacks cannot undo cancellation.
            await self.refresh(payment)
        elif status in {"CONFIRMED", "CANCELED", "CHARGEBACKED"}:
            pricing = self.retort.load(payment.pricing, PriceDetailsDto)
            if Decimal(str(data["amount"])) != pricing.final_amount or data["currency"] != "RUB":
                raise ValueError("Recurring charge amount/currency mismatch")
            payment_id = UUID(data["id"])
            transaction = await self.transaction_dao.get_by_payment_id(payment_id)
            if transaction and transaction.user_id != payment.user_id:
                raise ValueError("Recurring charge belongs to another user")
            if status == "CHARGEBACKED":
                if not transaction:
                    raise ValueError("Refund arrived before its charge")
                transaction.status = TransactionStatus.REFUNDED
                await self.transaction_dao.update(transaction)
            elif status == "CONFIRMED" and (
                not transaction
                or transaction.status
                not in {TransactionStatus.COMPLETED, TransactionStatus.REFUNDED}
            ):
                if not transaction:
                    transaction = await self.transaction_dao.create(
                        TransactionDto(
                            payment_id=payment_id,
                            user_id=payment.user_id,
                            status=TransactionStatus.PENDING,
                            purchase_type=PurchaseType.RENEW,
                            gateway_type=PaymentGatewayType.PLATEGA,
                            gateway_display_name=payment.display_name,
                            payment_method="6",
                            pricing=pricing,
                            currency=Currency.RUB,
                            plan_snapshot=self.retort.load(payment.plan_snapshot, PlanSnapshotDto),
                        )
                    )
                await self._fulfill(event, payment, transaction)
                transaction.status = TransactionStatus.COMPLETED
                await self.transaction_dao.update(transaction)
            elif status == "CANCELED" and not transaction:
                await self.transaction_dao.create(
                    TransactionDto(
                        payment_id=payment_id,
                        user_id=payment.user_id,
                        status=TransactionStatus.CANCELED,
                        purchase_type=PurchaseType.RENEW,
                        gateway_type=PaymentGatewayType.PLATEGA,
                        gateway_display_name=payment.display_name,
                        payment_method="6",
                        pricing=pricing,
                        currency=Currency.RUB,
                        plan_snapshot=self.retort.load(payment.plan_snapshot, PlanSnapshotDto),
                    )
                )
            await self.refresh(payment)
        else:
            raise ValueError(f"Unsupported recurring status: {status}")
        event.processed_at = datetime_now()
        event.error = None
        await self.session.commit()
        if status == "CONFIRMED":
            user = await self.user_dao.get_by_id(payment.user_id)
            if user:
                try:
                    await self.notifier.notify_user(user, i18n_key="ntf-autopay-paid")
                    transaction = await self.transaction_dao.get_by_payment_id(UUID(data["id"]))
                    if transaction and transaction.status == TransactionStatus.COMPLETED:
                        await self.assign_referral_rewards.system(
                            AssignReferralRewardsDto(user, transaction)
                        )
                except Exception:
                    logger.exception("Autopay succeeded; notification/referral processing failed")
        elif status in {"CANCELED", "SUBSCRIPTION_PAST_DUE", "SUBSCRIPTION_FAILED"}:
            user = await self.user_dao.get_by_id(payment.user_id)
            if user:
                try:
                    await self.notifier.notify_user(user, i18n_key="ntf-autopay-failed")
                except Exception:
                    logger.exception("Could not deliver autopay failure notification")

    async def _fulfill(
        self, event: RecurringPaymentEvent, payment: RecurringPayment, transaction: TransactionDto
    ) -> None:
        user = await self.user_dao.get_by_id(payment.user_id)
        if not user:
            raise ValueError("Autopay user no longer exists")
        plan = transaction.plan_snapshot
        if event.target is None:
            current = await self.subscription_dao.get_current(user.id)
            renew = (
                current is not None and not current.is_trial and current.plan_snapshot.id == plan.id
            )
            base = max(current.expire_at, datetime_now()) if renew and current else datetime_now()
            target = SubscriptionDto(
                user_remna_id=current.user_remna_id if current else None,
                panel_user_id=current.panel_user_id if current else None,
                status=current.status
                if renew and current and current.status == SubscriptionStatus.DISABLED
                else SubscriptionStatus.ACTIVE,
                disabled_by_channel_leave=current.disabled_by_channel_leave
                if renew and current
                else False,
                traffic_limit=plan.traffic_limit,
                device_limit=plan.device_limit,
                traffic_limit_strategy=plan.traffic_limit_strategy,
                tag=plan.tag,
                internal_squads=plan.internal_squads,
                external_squad=plan.external_squad,
                expire_at=base + timedelta(days=plan.duration),
                url=current.url if current else "",
                plan_snapshot=plan,
            )
            event.target = {
                "subscription": orjson.loads(orjson.dumps(self.retort.dump(target))),
                "current_id": current.id if current else None,
                "renew": renew,
                "short_uuid": uuid4().hex[:16],
            }
            transaction.purchase_type = (
                PurchaseType.RENEW
                if renew
                else PurchaseType.CHANGE
                if current
                else PurchaseType.NEW
            )
            await self.transaction_dao.update(transaction)
            # A retry reuses this absolute expiration even after a lost panel response.
            await self.session.commit()
        target = self.retort.load(event.target["subscription"], SubscriptionDto)
        if target.user_remna_id is None and target.panel_user_id is None:
            remote = await self.remnawave.create_user(
                replace(user, email=payment.email or user.email),
                subscription=target,
                short_uuid=event.target["short_uuid"],
            )
            target.user_remna_id = remote.uuid
            target.panel_user_id = remote.id
            target.url = remote.subscription_url
        else:
            await self.remnawave.update_user_subscription(
                subscription_ref(target), subscription=target, reset_traffic=False
            )
        if payment.email:
            await self.remnawave.update_user_email(subscription_ref(target), payment.email)
        await self._reset_traffic(event, target, transaction)
        if event.target["renew"]:
            target.id = event.target["current_id"]
            # Trackable DTOs start clean after loading; update through the existing DTO.
            existing = await self.subscription_dao.get_by_id(target.id)
            if not existing:
                raise ValueError("Subscription disappeared during autopay fulfillment")
            for field in (
                "expire_at",
                "status",
                "is_trial",
                "plan_snapshot",
                "traffic_limit",
                "device_limit",
                "traffic_limit_strategy",
                "tag",
                "internal_squads",
                "external_squad",
            ):
                setattr(existing, field, getattr(target, field))
            await self.subscription_dao.update(existing)
        else:
            if event.target["current_id"]:
                await self.subscription_dao.update_status(
                    event.target["current_id"], SubscriptionStatus.DELETED
                )
            await self.subscription_dao.create(target, user.id)
        await self.user_dao.set_trial_available(user.id, False)

    async def _reset_traffic(
        self, event: RecurringPaymentEvent, target: SubscriptionDto, transaction: TransactionDto
    ) -> None:
        if event.target is None:
            raise ValueError("Missing persisted entitlement target")
        if transaction.plan_snapshot.duration < 7 or event.target.get("reset_started"):
            return
        # Reset is not safely repeatable after a lost response: attempt once per charge.
        event.target = {**event.target, "reset_started": True}
        await self.session.commit()
        try:
            await self.remnawave.reset_traffic(subscription_ref(target))
        except Exception:
            try:
                await self.notifier.notify_admins(
                    MessagePayloadDto(
                        i18n_key="ntf-autopay-reset-review",
                        i18n_kwargs={
                            "payment_id": str(transaction.payment_id),
                            "user_id": transaction.user_id,
                        },
                    )
                )
            except Exception:
                logger.exception("Could not notify admins about an uncertain traffic reset")
            raise

    async def pending_events(self) -> list[str]:
        return list(
            (
                await self.session.scalars(
                    select(RecurringPaymentEvent.id)
                    .where(RecurringPaymentEvent.processed_at.is_(None))
                    .order_by(RecurringPaymentEvent.updated_at)
                    .limit(100)
                )
            ).all()
        )

    @staticmethod
    def _datetime(value: Any) -> datetime | None:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
