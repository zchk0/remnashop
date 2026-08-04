from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from adaptix.conversion import ConversionRetort
from loguru import logger
from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.common.dao import PromocodeDao
from src.application.dto import (
    PromocodeActivationDetailDto,
    PromocodeActivationDto,
    PromocodeDetailStatisticsDto,
    PromocodeDto,
    PromocodeStatisticsDto,
)
from src.core.enums import (
    PromocodeActivationEventStatus,
    PromocodeActivationStatus,
    PromocodeRewardType,
)
from src.core.exceptions import PromocodeAlreadyActivatedError, PromocodeNotAvailableError
from src.core.utils.time import datetime_now
from src.infrastructure.database.models import User
from src.infrastructure.database.models.promocode import Promocode, PromocodeActivation


class PromocodeDaoImpl(PromocodeDao):
    def __init__(self, session: AsyncSession, conversion_retort: ConversionRetort) -> None:
        self.session = session
        self._to_dto = conversion_retort.get_converter(Promocode, PromocodeDto)
        self._to_dto_list = conversion_retort.get_converter(list[Promocode], list[PromocodeDto])
        self._act_to_dto = conversion_retort.get_converter(
            PromocodeActivation, PromocodeActivationDto
        )

    async def create(self, promocode: PromocodeDto) -> PromocodeDto:
        db = Promocode(
            code=promocode.code.upper(),
            is_active=promocode.is_active,
            reward_type=promocode.reward_type,
            reward=promocode.reward,
            plan_snapshot=promocode.plan_snapshot,
            availability=promocode.availability,
            expires_at=promocode.expires_at,
            max_activations=promocode.max_activations,
            is_reusable=promocode.is_reusable,
        )
        self.session.add(db)
        try:
            await self.session.flush()
        except IntegrityError:
            raise ValueError(f"Promocode with code '{promocode.code}' already exists")
        logger.debug(f"Promocode '{promocode.code}' created with id={db.id}")
        return self._to_dto(db)

    async def update(self, promocode: PromocodeDto) -> Optional[PromocodeDto]:
        db = await self.session.scalar(
            select(Promocode)
            .where(
                Promocode.id == promocode.id,
                Promocode.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if not db:
            logger.warning(f"Promocode id={promocode.id} not found for update")
            return None
        for key, value in promocode.changed_data.items():
            if key != "deleted_at" and hasattr(db, key):
                if key == "code":
                    value = value.upper()
                setattr(db, key, value)
        await self.session.flush()
        # Reload eagerly: the server-side ``onupdate`` expires ``updated_at`` after the
        # UPDATE, and the sync DTO converter cannot lazy-load it inside the async session.
        await self.session.refresh(db)
        logger.debug(f"Promocode id={promocode.id} updated")
        return self._to_dto(db)

    async def delete(self, promocode_id: int) -> bool:
        db = await self.session.scalar(
            select(Promocode).where(Promocode.id == promocode_id).with_for_update()
        )
        if db is None:
            logger.debug(f"Promocode id={promocode_id} not found for deletion")
            return False

        activation_id = await self.session.scalar(
            select(PromocodeActivation.id)
            .where(PromocodeActivation.promocode_id == promocode_id)
            .limit(1)
        )
        if activation_id is not None:
            db.is_active = False
            db.deleted_at = datetime_now()
            await self.session.flush()
            logger.debug(
                f"Promocode id={promocode_id} soft-deleted to preserve activation history"
            )
            return True

        await self.session.execute(delete(Promocode).where(Promocode.id == promocode_id))
        logger.debug(f"Unused promocode id={promocode_id} deleted")
        return True

    async def get_by_id(self, promocode_id: int) -> Optional[PromocodeDto]:
        db = await self.session.get(Promocode, promocode_id)
        return self._to_dto(db) if db else None

    async def get_by_code(self, code: str) -> Optional[PromocodeDto]:
        stmt = select(Promocode).where(Promocode.code == code.upper())
        db = await self.session.scalar(stmt)
        return self._to_dto(db) if db else None

    async def get_by_code_for_update(self, code: str) -> Optional[PromocodeDto]:
        stmt = (
            select(Promocode)
            .where(Promocode.code == code.strip().upper())
            .with_for_update()
        )
        db = await self.session.scalar(stmt)
        return self._to_dto(db) if db else None

    async def get_list(self, limit: int = 100, offset: int = 0) -> list[PromocodeDto]:
        stmt = (
            select(Promocode)
            .where(Promocode.deleted_at.is_(None))
            .order_by(Promocode.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.scalars(stmt)
        return self._to_dto_list(list(result.all()))

    async def get_count(self) -> int:
        result = await self.session.scalar(
            select(func.count(Promocode.id)).where(Promocode.deleted_at.is_(None))
        )
        return result or 0

    async def get_activations_count(self, promocode_id: int) -> int:
        result = await self.session.scalar(
            select(func.count(PromocodeActivation.id)).where(
                PromocodeActivation.promocode_id == promocode_id
            )
        )
        return result or 0

    async def get_statistics(self) -> PromocodeStatisticsDto:
        now = datetime_now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)

        promo_counts = (
            (
                await self.session.execute(
                    select(
                        func.count().label("total"),
                        func.sum(case((Promocode.is_active, 1), else_=0)).label("active"),
                    )
                    .select_from(Promocode)
                    .where(Promocode.deleted_at.is_(None))
                )
            )
            .mappings()
            .one()
        )

        activated_at = PromocodeActivation.activated_at
        activation_counts = (
            (
                await self.session.execute(
                    select(
                        func.count().label("total"),
                        func.sum(case((activated_at >= today_start, 1), else_=0)).label("today"),
                        func.sum(case((activated_at >= week_ago, 1), else_=0)).label("week"),
                        func.sum(case((activated_at >= month_ago, 1), else_=0)).label("month"),
                    )
                    .select_from(PromocodeActivation)
                    .where(PromocodeActivation.status == PromocodeActivationStatus.APPLIED)
                )
            )
            .mappings()
            .one()
        )

        by_type_rows = (
            (
                await self.session.execute(
                    select(
                        PromocodeActivation.reward_type_snapshot,
                        func.count(PromocodeActivation.id).label("count"),
                        func.coalesce(func.sum(PromocodeActivation.reward_snapshot), 0).label(
                            "reward_sum"
                        ),
                    )
                    .where(PromocodeActivation.status == PromocodeActivationStatus.APPLIED)
                    .group_by(PromocodeActivation.reward_type_snapshot)
                )
            )
            .mappings()
            .all()
        )

        counts: dict[PromocodeRewardType, int] = {}
        reward_sums: dict[PromocodeRewardType, int] = {}
        for row in by_type_rows:
            reward_type = row["reward_type_snapshot"]
            counts[reward_type] = int(row["count"] or 0)
            reward_sums[reward_type] = int(row["reward_sum"] or 0)

        return PromocodeStatisticsDto(
            total_promocodes=int(promo_counts["total"] or 0),
            active_promocodes=int(promo_counts["active"] or 0),
            total_activations=int(activation_counts["total"] or 0),
            activations_today=int(activation_counts["today"] or 0),
            activations_week=int(activation_counts["week"] or 0),
            activations_month=int(activation_counts["month"] or 0),
            issued_days=reward_sums.get(PromocodeRewardType.DURATION, 0),
            issued_traffic=reward_sums.get(PromocodeRewardType.TRAFFIC, 0),
            issued_devices=reward_sums.get(PromocodeRewardType.DEVICES, 0),
            issued_subscriptions=counts.get(PromocodeRewardType.SUBSCRIPTION, 0),
            issued_personal_discounts=counts.get(PromocodeRewardType.PERSONAL_DISCOUNT, 0),
            issued_purchase_discounts=counts.get(PromocodeRewardType.PURCHASE_DISCOUNT, 0),
        )

    async def get_detail_statistics(
        self, promocode_id: int
    ) -> Optional[PromocodeDetailStatisticsDto]:
        promo = await self.session.get(Promocode, promocode_id)
        if not promo:
            return None

        now = datetime_now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)

        activated_at = PromocodeActivation.activated_at
        counts = (
            (
                await self.session.execute(
                    select(
                        func.count().label("total"),
                        func.sum(case((activated_at >= today_start, 1), else_=0)).label("today"),
                        func.sum(case((activated_at >= week_ago, 1), else_=0)).label("week"),
                        func.sum(case((activated_at >= month_ago, 1), else_=0)).label("month"),
                    ).where(
                        PromocodeActivation.promocode_id == promocode_id,
                        PromocodeActivation.status == PromocodeActivationStatus.APPLIED,
                    )
                )
            )
            .mappings()
            .one()
        )

        return PromocodeDetailStatisticsDto(
            code=promo.code,
            reward_type=promo.reward_type,
            reward=promo.reward,
            plan_snapshot=promo.plan_snapshot,
            is_active=promo.is_active,
            is_reusable=promo.is_reusable,
            created_at=promo.created_at,
            expires_at=promo.expires_at,
            max_activations=promo.max_activations,
            total_activations=int(counts["total"] or 0),
            activations_today=int(counts["today"] or 0),
            activations_week=int(counts["week"] or 0),
            activations_month=int(counts["month"] or 0),
        )

    async def get_activation_by_user(
        self, promocode_id: int, user_id: int
    ) -> Optional[PromocodeActivationDto]:
        stmt = select(PromocodeActivation).where(
            PromocodeActivation.promocode_id == promocode_id,
            PromocodeActivation.user_id == user_id,
        )
        db = await self.session.scalar(stmt)
        return self._act_to_dto(db) if db else None

    async def get_activation_by_request_id(
        self,
        request_id: UUID,
        for_update: bool = False,
    ) -> Optional[PromocodeActivationDto]:
        stmt = select(PromocodeActivation).where(
            PromocodeActivation.request_id == request_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        db = await self.session.scalar(stmt)
        return self._act_to_dto(db) if db else None

    async def get_pending_activation_by_user(
        self,
        user_id: int,
    ) -> Optional[PromocodeActivationDto]:
        stmt = select(PromocodeActivation).where(
            PromocodeActivation.user_id == user_id,
            PromocodeActivation.status.in_(
                (
                    PromocodeActivationStatus.PENDING,
                    PromocodeActivationStatus.FAILED,
                    PromocodeActivationStatus.REQUIRES_REVIEW,
                )
            ),
        )
        db = await self.session.scalar(stmt)
        return self._act_to_dto(db) if db else None

    async def get_pending_activations(
        self,
        limit: int = 100,
    ) -> list[PromocodeActivationDto]:
        stmt = (
            select(PromocodeActivation)
            .where(
                PromocodeActivation.status == PromocodeActivationStatus.PENDING,
                or_(
                    PromocodeActivation.next_retry_at.is_(None),
                    PromocodeActivation.next_retry_at <= datetime_now(),
                ),
            )
            .order_by(
                func.coalesce(
                    PromocodeActivation.next_retry_at,
                    PromocodeActivation.activated_at,
                ),
                PromocodeActivation.id,
            )
            .limit(limit)
        )
        rows = await self.session.scalars(stmt)
        return [self._act_to_dto(row) for row in rows.all()]

    async def claim_pending_activation_events(
        self,
        lease_until: datetime,
        limit: int = 100,
    ) -> list[PromocodeActivationDto]:
        due_ids = (
            select(PromocodeActivation.id)
            .where(
                PromocodeActivation.event_status
                == PromocodeActivationEventStatus.PENDING,
                or_(
                    PromocodeActivation.event_next_retry_at.is_(None),
                    PromocodeActivation.event_next_retry_at <= datetime_now(),
                ),
            )
            .order_by(
                func.coalesce(
                    PromocodeActivation.event_next_retry_at,
                    PromocodeActivation.activated_at,
                ),
                PromocodeActivation.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = await self.session.scalars(
            update(PromocodeActivation)
            .where(PromocodeActivation.id.in_(due_ids))
            .values(event_next_retry_at=lease_until)
            .returning(PromocodeActivation)
        )
        return [self._act_to_dto(row) for row in rows.all()]

    async def lock_activation_user(self, user_id: int) -> None:
        await self.session.execute(
            select(User.id).where(User.id == user_id).with_for_update()
        )

    async def lock_activation_request(self, request_id: UUID) -> None:
        # A transaction-scoped advisory lock also serializes the first insertion,
        # when there is no activation row available for SELECT FOR UPDATE yet.
        lock_key = request_id.int & ((1 << 63) - 1)
        await self.session.execute(select(func.pg_advisory_xact_lock(lock_key)))

    async def get_activations_by_user(
        self, user_id: int, limit: int = 100, offset: int = 0
    ) -> list[PromocodeActivationDetailDto]:
        stmt = (
            select(PromocodeActivation)
            .where(
                PromocodeActivation.user_id == user_id,
                PromocodeActivation.status == PromocodeActivationStatus.APPLIED,
            )
            .order_by(PromocodeActivation.activated_at.desc(), PromocodeActivation.id.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self.session.scalars(stmt)).all()
        return [
            PromocodeActivationDetailDto(
                activation_id=activation.id,
                promocode_id=activation.promocode_id,
                code=activation.code_snapshot,
                reward_type=activation.reward_type_snapshot,
                reward=activation.reward_snapshot,
                plan_snapshot=activation.plan_snapshot,
                activated_at=activation.activated_at,
            )
            for activation in rows
        ]

    async def get_activations_count_by_user(self, user_id: int) -> int:
        result = await self.session.scalar(
            select(func.count(PromocodeActivation.id)).where(
                PromocodeActivation.user_id == user_id,
                PromocodeActivation.status == PromocodeActivationStatus.APPLIED,
            )
        )
        return result or 0

    async def create_activation(
        self,
        activation: PromocodeActivationDto,
        max_activations: Optional[int] = None,
        is_reusable: bool = False,
    ) -> PromocodeActivationDto:
        # Lock the promocode row so the activation-limit and per-user uniqueness checks
        # below run race-free against concurrent activations of the same promocode.
        if max_activations is not None or not is_reusable:
            await self.session.execute(
                select(Promocode.id)
                .where(Promocode.id == activation.promocode_id)
                .with_for_update()
            )

        if max_activations is not None:
            count_result = await self.session.execute(
                select(func.count(PromocodeActivation.id)).where(
                    PromocodeActivation.promocode_id == activation.promocode_id,
                )
            )
            count = count_result.scalar() or 0
            if count >= max_activations:
                raise PromocodeNotAvailableError("Promocode activation limit reached")

        if not is_reusable:
            existing = await self.session.scalar(
                select(PromocodeActivation.id).where(
                    PromocodeActivation.promocode_id == activation.promocode_id,
                    PromocodeActivation.user_id == activation.user_id,
                )
            )
            if existing is not None:
                raise PromocodeAlreadyActivatedError(
                    f"Promocode '{activation.promocode_id}' already activated "
                    f"by user '{activation.user_id}'"
                )

        db = PromocodeActivation(
            promocode_id=activation.promocode_id,
            user_id=activation.user_id,
            activated_at=activation.activated_at,
            code_snapshot=activation.code_snapshot,
            reward_type_snapshot=activation.reward_type_snapshot,
            reward_snapshot=activation.reward_snapshot,
            plan_snapshot=activation.plan_snapshot,
            request_id=activation.request_id,
            status=activation.status,
            remote_action=activation.remote_action,
            target_remna_id=activation.target_remna_id,
            reset_traffic=activation.reset_traffic,
            last_error=activation.last_error,
            attempt_count=activation.attempt_count,
            next_retry_at=activation.next_retry_at,
            event_status=activation.event_status,
            event_attempt_count=activation.event_attempt_count,
            event_next_retry_at=activation.event_next_retry_at,
            event_last_error=activation.event_last_error,
            event_sent_at=activation.event_sent_at,
        )
        self.session.add(db)
        await self.session.flush()
        logger.debug(
            f"PromocodeActivation created: promocode_id={activation.promocode_id}, "
            f"user_id={activation.user_id}"
        )
        return self._act_to_dto(db)

    async def mark_activation_applied(self, request_id: UUID) -> PromocodeActivationDto:
        db = await self.session.scalar(
            update(PromocodeActivation)
            .where(PromocodeActivation.request_id == request_id)
            .values(
                status=PromocodeActivationStatus.APPLIED,
                last_error=None,
                next_retry_at=None,
                event_status=PromocodeActivationEventStatus.PENDING,
                event_attempt_count=0,
                event_next_retry_at=None,
                event_last_error=None,
            )
            .returning(PromocodeActivation)
        )
        if db is None:
            raise RuntimeError(f"Promocode activation request '{request_id}' not found")
        return self._act_to_dto(db)

    async def record_activation_failure(
        self,
        request_id: UUID,
        error: str,
        status: PromocodeActivationStatus,
        attempt_count: int,
        next_retry_at: Optional[datetime],
    ) -> None:
        await self.session.execute(
            update(PromocodeActivation)
            .where(PromocodeActivation.request_id == request_id)
            .values(
                status=status,
                last_error=error[:1000],
                attempt_count=attempt_count,
                next_retry_at=next_retry_at,
            )
        )

    async def mark_activation_event_sent(
        self,
        activation_id: int,
        sent_at: datetime,
    ) -> None:
        await self.session.execute(
            update(PromocodeActivation)
            .where(
                PromocodeActivation.id == activation_id,
                PromocodeActivation.event_status
                == PromocodeActivationEventStatus.PENDING,
            )
            .values(
                event_status=PromocodeActivationEventStatus.SENT,
                event_next_retry_at=None,
                event_last_error=None,
                event_sent_at=sent_at,
            )
        )

    async def record_activation_event_failure(
        self,
        activation_id: int,
        error: str,
        attempt_count: int,
        next_retry_at: Optional[datetime],
    ) -> None:
        status = (
            PromocodeActivationEventStatus.FAILED
            if next_retry_at is None
            else PromocodeActivationEventStatus.PENDING
        )
        await self.session.execute(
            update(PromocodeActivation)
            .where(
                PromocodeActivation.id == activation_id,
                PromocodeActivation.event_status
                == PromocodeActivationEventStatus.PENDING,
            )
            .values(
                event_status=status,
                event_attempt_count=attempt_count,
                event_next_retry_at=next_retry_at,
                event_last_error=error[:1000],
            )
        )
