"""
ToBeVPN device management, auth-token flow, TV pairing, and panel proxy endpoints.

These endpoints are consumed by the Android/TV client apps and keep
sensitive credentials (Remnawave API token) server-side.
"""

import hashlib
import html
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel, EmailStr
from remnapy import RemnawaveSDK
from remnapy.exceptions import ConflictError, NotFoundError
from remnapy.models import CreateUserRequestDto, UpdateUserRequestDto, UserResponseDto
from remnapy.models.hwid import HwidDeviceDto

from src.application.common import BotService, Cryptographer, Notifier, Remnawave
from src.application.common.dao import (
    AuthTokenDao,
    DeviceSessionDao,
    LinkedDeviceDao,
    PaymentGatewayDao,
    PlanDao,
    SubscriptionDao,
    TvPairingDao,
    UserDao,
)
from src.application.common.uow import UnitOfWork
from src.application.dto import (
    MessagePayloadDto,
    PaymentGatewayDto,
    PlanDto,
    PlanDurationDto,
    RemnaSubscriptionDto,
    SubscriptionDto,
    UserDto,
)
from src.application.dto.device import (
    AuthTokenDto,
    DeviceSessionDto,
    LinkedDeviceDto,
    TvPairingCodeDto,
)
from src.application.services import PricingService
from src.application.services.device_binding import bind_linked_device
from src.application.use_cases.plan.queries.match import MatchPlan, MatchPlanDto
from src.application.use_cases.user.queries.plans import GetAvailablePlans
from src.core.config import AppConfig
from src.core.constants import TV_PAIRING_TTL_SECONDS
from src.core.enums import Deeplink, PlanAvailability, PurchaseType
from src.core.utils.converters import days_to_datetime, gb_to_bytes
from src.core.utils.device_description import (
    append_device_id_to_description,
    append_saved_anon_traffic_to_description,
)


@dataclass(kw_only=True)
class DeviceAuthContext:
    device_id: Optional[str] = None
    telegram_id: Optional[int] = None
    panel_user_uuid: Optional[str] = None
    short_uuid: Optional[str] = None
    platform: Optional[str] = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _extract_bearer_token(authorization: str) -> Optional[str]:
    auth_scheme, _, token = authorization.partition(" ")
    if auth_scheme.lower() != "bearer" or not token:
        return None
    return token


def _build_device_auth_unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _is_expired(expires_at: datetime) -> bool:
    return expires_at <= _utcnow()


def _build_session_response(
    access_token: str,
    refresh_token: str,
    access_expires_at: datetime,
    refresh_expires_at: datetime,
    linked_device: Optional[LinkedDeviceDto] = None,
) -> dict:
    now = _utcnow()
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": max(0, int((access_expires_at - now).total_seconds())),
        "refresh_expires_in": max(0, int((refresh_expires_at - now).total_seconds())),
        "device_id": linked_device.device_id if linked_device else None,
        "telegram_id": linked_device.telegram_id if linked_device else None,
        "panel_user_uuid": linked_device.panel_user_uuid if linked_device else None,
        "short_uuid": linked_device.short_uuid if linked_device else None,
        "is_linked": bool(
            linked_device
            and (linked_device.telegram_id is not None or linked_device.panel_user_uuid)
        ),
    }


def _generate_session_tokens(
    device_id: str,
    platform: Optional[str],
    integrity_token: Optional[str],
    config: AppConfig,
    cryptographer: Cryptographer,
    current_session: Optional[DeviceSessionDto] = None,
) -> tuple[DeviceSessionDto, str, str]:
    now = _utcnow()
    access_token = secrets.token_urlsafe(32)
    refresh_token = secrets.token_urlsafe(48)
    session = DeviceSessionDto(
        device_id=device_id,
        access_token_hash=cryptographer.get_hash(access_token),
        refresh_token_hash=cryptographer.get_hash(refresh_token),
        access_expires_at=now + timedelta(seconds=config.tobevpn.access_token_ttl_seconds),
        refresh_expires_at=now + timedelta(seconds=config.tobevpn.refresh_token_ttl_seconds),
        platform=platform or (current_session.platform if current_session else None),
        integrity_token_hash=(
            cryptographer.get_hash(integrity_token)
            if integrity_token
            else (current_session.integrity_token_hash if current_session else None)
        ),
        last_used_at=now,
        revoked_at=None,
    )
    return session, access_token, refresh_token


def _merge_linked_device(
    device: LinkedDeviceDto,
    *,
    device_name: Optional[str] = None,
    device_type: Optional[str] = None,
    platform: Optional[str] = None,
) -> LinkedDeviceDto:
    return replace(
        device,
        device_name=device_name if device_name is not None else device.device_name,
        device_type=device_type if device_type is not None else device.device_type,
        platform=platform if platform is not None else device.platform,
    )


def _resolve_device_id(auth: DeviceAuthContext, device_id: Optional[str]) -> str:
    if auth.device_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current device session is missing device identity",
        )

    if device_id is not None and device_id != auth.device_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="device_id does not match current device session",
        )

    return auth.device_id


def _resolve_unlink_device_id(auth: DeviceAuthContext, device_id: Optional[str]) -> str:
    if auth.device_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current device session is missing device identity",
        )

    if device_id is not None:
        return device_id

    return auth.device_id


def _resolve_telegram_id(auth: DeviceAuthContext, telegram_id: Optional[int]) -> int:
    if auth.telegram_id is not None:
        if telegram_id is not None and telegram_id != auth.telegram_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="telegram_id does not match current device session",
            )
        return auth.telegram_id

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Current device session is not linked to a Telegram user",
    )


@inject
async def get_device_auth_context(
    config: FromDishka[AppConfig],
    cryptographer: FromDishka[Cryptographer],
    session_dao: FromDishka[DeviceSessionDao],
    device_dao: FromDishka[LinkedDeviceDao],
    authorization: Annotated[str, Header(alias="Authorization")] = "",
) -> DeviceAuthContext:
    if not config.tobevpn.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ToBeVPN integration is not configured",
        )

    token = _extract_bearer_token(authorization)
    if not token:
        raise _build_device_auth_unauthorized("Missing bearer token")

    token_hash = cryptographer.get_hash(token)
    session = await session_dao.get_by_access_token_hash(token_hash)
    if not session or session.revoked_at or _is_expired(session.access_expires_at):
        logger.warning("Invalid or expired ToBeVPN device access token provided")
        raise _build_device_auth_unauthorized("Invalid or expired access token")

    linked_device = await device_dao.get_by_device_id(session.device_id)
    return DeviceAuthContext(
        device_id=session.device_id,
        telegram_id=linked_device.telegram_id if linked_device else None,
        panel_user_uuid=linked_device.panel_user_uuid if linked_device else None,
        short_uuid=linked_device.short_uuid if linked_device else None,
        platform=session.platform,
    )


router = APIRouter(prefix="/api")


ANONYMOUS_TRIAL_PRIORITY: dict[PlanAvailability, int] = {
    PlanAvailability.NEW: 2,
    PlanAvailability.ALL: 1,
}


def _get_plan_duration_days(plan: PlanDto) -> Optional[int]:
    if not plan.durations:
        return None

    duration = sorted(plan.durations, key=lambda d: d.order_index)[0]
    return duration.days


def _get_anonymous_trial_traffic_limit_bytes(config: AppConfig, plan: PlanDto) -> int:
    if config.tobevpn.anonymous_trial_traffic_gb > 0:
        return gb_to_bytes(config.tobevpn.anonymous_trial_traffic_gb)
    return gb_to_bytes(plan.traffic_limit)


def _get_effective_anonymous_trial_traffic_limit_bytes(
    traffic_limit_bytes: int,
    saved_anon_traffic: int,
) -> int:
    if traffic_limit_bytes <= 0:
        return 0

    return max(traffic_limit_bytes - saved_anon_traffic, 1)


async def _get_anonymous_trial_plan(plan_dao: PlanDao) -> Optional[PlanDto]:
    active_trials = await plan_dao.get_active_trial_plans()

    eligible_plans = [
        (ANONYMOUS_TRIAL_PRIORITY[plan.availability], plan.order_index, plan)
        for plan in active_trials
        if plan.availability in ANONYMOUS_TRIAL_PRIORITY and plan.durations
    ]

    if not eligible_plans:
        logger.info("No active trial plan available for ToBeVPN anonymous user")
        return None

    eligible_plans.sort(key=lambda item: (-item[0], item[1]))
    plan = eligible_plans[0][2]
    logger.info(f"Selected ToBeVPN trial plan '{plan.id}' with availability '{plan.availability}'")
    return plan


def _build_trial_config_data(config: AppConfig, plan: PlanDto) -> dict:
    duration_days = _get_plan_duration_days(plan)
    internal_squad_uuids = [str(uuid) for uuid in plan.internal_squads]

    return {
        "trial_plan_id": plan.id,
        "trial_plan_name": plan.name,
        "free_squad_uuid": internal_squad_uuids[0] if internal_squad_uuids else None,
        "free_squad_uuids": internal_squad_uuids,
        "external_squad_uuid": str(plan.external_squad) if plan.external_squad else None,
        "free_trial_traffic_bytes": _get_anonymous_trial_traffic_limit_bytes(config, plan),
        "free_trial_days": duration_days,
    }


def _build_device_username(device_id: str) -> str:
    digest = hashlib.sha256(device_id.encode()).hexdigest()[:32]
    return f"app_{digest}"


def _build_anonymous_description(
    plan: PlanDto,
    device_id: str,
    saved_anon_traffic: int = 0,
) -> str:
    description = plan.description or f"ToBeVPN trial: {plan.name}"
    description = append_device_id_to_description(description, device_id)
    return append_saved_anon_traffic_to_description(description, saved_anon_traffic)


async def _ensure_panel_user_device_comment(
    remnawave_sdk: RemnawaveSDK,
    user: UserResponseDto,
    device_id: str,
    saved_anon_traffic: int = 0,
) -> None:
    description = append_device_id_to_description(user.description, device_id)
    description = append_saved_anon_traffic_to_description(description, saved_anon_traffic)
    if description == (user.description or "").strip():
        return

    await remnawave_sdk.users.update_user(
        UpdateUserRequestDto(uuid=user.uuid, description=description)
    )


def _get_plan_purchase_type(
    plan: PlanDto,
    current_subscription: Optional[SubscriptionDto],
    renewable_plan_id: Optional[int],
) -> PurchaseType:
    if not current_subscription:
        return PurchaseType.NEW

    if renewable_plan_id == plan.id:
        return PurchaseType.RENEW

    return PurchaseType.CHANGE


async def _build_duration_data(
    plan_id: Optional[int],
    duration: PlanDurationDto,
    user: UserDto,
    gateways: list[PaymentGatewayDto],
    pricing_service: PricingService,
    bot_service: BotService,
) -> dict:
    if plan_id is None:
        raise ValueError("Plan id is required to build ToBeVPN purchase link")

    prices_by_currency = {price.currency: price for price in duration.prices}
    payment_methods = []
    bot_start_param = f"{Deeplink.BUY.with_underscore}{plan_id}_{duration.days}"

    for gateway in gateways:
        price = prices_by_currency.get(gateway.currency)
        if price is None:
            continue

        pricing = pricing_service.calculate(user, price.price, gateway.currency)
        payment_methods.append(
            {
                "gateway_type": gateway.type.value,
                "currency": gateway.currency.value,
                "original_amount": str(pricing.original_amount),
                "final_amount": str(pricing.final_amount),
                "discount_percent": pricing.discount_percent,
            }
        )

    return {
        "id": duration.id,
        "days": duration.days,
        "order_index": duration.order_index,
        "bot_start_param": bot_start_param,
        "bot_payment_url": await bot_service.get_purchase_url(plan_id, duration.days),
        "prices": [
            {
                "currency": price.currency.value,
                "amount": str(price.price),
            }
            for price in duration.prices
        ],
        "payment_methods": payment_methods,
    }


async def _build_purchase_plan_data(
    plan: PlanDto,
    user: UserDto,
    current_subscription: Optional[SubscriptionDto],
    renewable_plan_id: Optional[int],
    gateways: list[PaymentGatewayDto],
    pricing_service: PricingService,
    bot_service: BotService,
) -> dict:
    purchase_type = _get_plan_purchase_type(plan, current_subscription, renewable_plan_id)

    return {
        "id": plan.id,
        "public_code": plan.public_code,
        "name": plan.name,
        "description": plan.description,
        "type": plan.type.value,
        "availability": plan.availability.value,
        "purchase_type": purchase_type.value,
        "traffic_limit": plan.traffic_limit,
        "traffic_limit_strategy": plan.traffic_limit_strategy.value,
        "device_limit": plan.device_limit,
        "tag": plan.tag,
        "order_index": plan.order_index,
        "internal_squad_uuids": [str(squad_uuid) for squad_uuid in plan.internal_squads],
        "external_squad_uuid": str(plan.external_squad) if plan.external_squad else None,
        "durations": [
            await _build_duration_data(
                plan_id=plan.id,
                duration=duration,
                user=user,
                gateways=gateways,
                pricing_service=pricing_service,
                bot_service=bot_service,
            )
            for duration in sorted(plan.durations, key=lambda item: item.order_index)
        ],
    }


def _datetime_to_iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _datetime_to_timestamp(value: Optional[datetime]) -> Optional[int]:
    return int(value.timestamp()) if value else None


def _build_current_plan_data(subscription: SubscriptionDto) -> dict:
    plan = subscription.plan_snapshot

    return {
        "current_plan": {
            "id": plan.id,
            "name": plan.name,
            "type": plan.type.value,
            "tag": plan.tag,
            "is_trial": plan.is_trial,
            "duration_days": plan.duration,
            "traffic_limit": plan.traffic_limit,
            "traffic_limit_bytes": gb_to_bytes(plan.traffic_limit),
            "traffic_limit_strategy": plan.traffic_limit_strategy.value,
            "device_limit": plan.device_limit,
            "internal_squad_uuids": [str(squad_uuid) for squad_uuid in plan.internal_squads],
            "external_squad_uuid": str(plan.external_squad) if plan.external_squad else None,
        },
        "subscription": {
            "id": subscription.id,
            "user_remna_id": str(subscription.user_remna_id),
            "status": subscription.current_status.value,
            "stored_status": subscription.status.value,
            "is_active": subscription.is_active,
            "is_expired": subscription.is_expired,
            "is_unlimited": subscription.is_unlimited,
            "is_trial": subscription.is_trial,
            "traffic_limit": subscription.traffic_limit,
            "traffic_limit_bytes": gb_to_bytes(subscription.traffic_limit),
            "traffic_limit_strategy": subscription.traffic_limit_strategy.value,
            "device_limit": subscription.device_limit,
            "expire_at": _datetime_to_iso(subscription.expire_at),
            "expire_at_ts": _datetime_to_timestamp(subscription.expire_at),
            "created_at": _datetime_to_iso(subscription.created_at),
            "created_at_ts": _datetime_to_timestamp(subscription.created_at),
            "updated_at": _datetime_to_iso(subscription.updated_at),
            "updated_at_ts": _datetime_to_timestamp(subscription.updated_at),
            "url": subscription.url,
        },
    }


async def _get_panel_user_by_telegram_id(
    telegram_id: int,
    remnawave: Remnawave,
) -> Optional[UserResponseDto]:
    panel_users = await remnawave.get_users_by_telegram_id(telegram_id)
    return panel_users[0] if panel_users else None


async def _get_anonymous_panel_user_by_device_id(
    device_id: str,
    remnawave_sdk: RemnawaveSDK,
) -> Optional[UserResponseDto]:
    try:
        return await remnawave_sdk.users.get_user_by_username(_build_device_username(device_id))
    except NotFoundError:
        return None


def _get_saved_anon_traffic(device: Optional[LinkedDeviceDto]) -> int:
    return int(device.anon_traffic_bytes or 0) if device else 0


def _is_linked_device_bound(device: Optional[LinkedDeviceDto]) -> bool:
    return bool(device and (device.telegram_id is not None or device.panel_user_uuid))


def _build_panel_user_data(
    user: UserResponseDto,
    *,
    extra_traffic_used_bytes: int = 0,
    anon_traffic_bytes: int = 0,
    traffic_limit_bytes: Optional[int] = None,
    trial_plan_id: Optional[int] = None,
    is_anonymous: bool = False,
) -> dict:
    anon_traffic_bytes = anon_traffic_bytes or extra_traffic_used_bytes
    data = {
        "short_uuid": str(user.short_uuid),
        "panel_user_uuid": str(user.uuid),
        "traffic_limit_bytes": traffic_limit_bytes
        if traffic_limit_bytes is not None
        else user.traffic_limit_bytes or 0,
        "traffic_used_bytes": int(user.used_traffic_bytes or 0) + extra_traffic_used_bytes,
        "anon_traffic_bytes": anon_traffic_bytes,
        "max_devices": user.hwid_device_limit or 0,
        "is_anonymous": is_anonymous,
        "telegram_id": user.telegram_id,
    }

    if trial_plan_id is not None:
        data["trial_plan_id"] = trial_plan_id

    return data


def _build_hwid_device_data(device: HwidDeviceDto) -> dict:
    return {
        "device_id": device.hwid,
        "hwid": device.hwid,
        "device_name": device.device_model,
        "device_type": "hwid",
        "platform": device.platform,
        "device_model": device.device_model,
        "user_agent": device.user_agent,
        "linked_at": None,
        "last_seen_at": None,
    }


def _get_device_limit(panel_user: UserResponseDto) -> int:
    return panel_user.hwid_device_limit or 0


def _ensure_subscription_short_uuid_access(auth: DeviceAuthContext, short_uuid: str) -> None:
    if auth.short_uuid is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current device session is not linked to a subscription",
        )

    if short_uuid != auth.short_uuid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="short_uuid does not match current device session",
        )


async def _get_panel_user_by_subscription_short_uuid(
    short_uuid: str,
    remnawave_sdk: RemnawaveSDK,
) -> Optional[UserResponseDto]:
    try:
        return await remnawave_sdk.users.get_user_by_short_uuid(short_uuid)
    except NotFoundError:
        return None


async def _get_panel_user_for_subscription_action(
    auth: DeviceAuthContext,
    short_uuid: str,
    remnawave: Remnawave,
    remnawave_sdk: RemnawaveSDK,
) -> Optional[UserResponseDto]:
    _ensure_subscription_short_uuid_access(auth, short_uuid)

    if auth.panel_user_uuid:
        try:
            panel_user = await remnawave.get_user_by_uuid(UUID(auth.panel_user_uuid))
        except ValueError:
            logger.warning(f"Invalid panel_user_uuid in device session: '{auth.panel_user_uuid}'")
            return None

        if panel_user and str(panel_user.short_uuid) != short_uuid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="short_uuid does not match current device session",
            )

        return panel_user

    return await _get_panel_user_by_subscription_short_uuid(short_uuid, remnawave_sdk)


def _get_panel_user_telegram_id(panel_user: UserResponseDto) -> Optional[int]:
    if panel_user.telegram_id is None:
        return None

    try:
        return int(panel_user.telegram_id)
    except (TypeError, ValueError):
        logger.warning(
            f"Invalid telegram_id '{panel_user.telegram_id}' for RemnaUser '{panel_user.uuid}'"
        )
        return None


async def _sync_subscription_from_panel_user(
    panel_user: UserResponseDto,
    user_dao: UserDao,
    subscription_dao: SubscriptionDao,
    remnawave: Remnawave,
) -> tuple[Optional[SubscriptionDto], bool]:
    telegram_id = _get_panel_user_telegram_id(panel_user)
    if telegram_id is None:
        return None, False

    user = await user_dao.get_by_telegram_id(telegram_id)
    if user is None:
        logger.warning(f"Local user for telegram '{telegram_id}' not found during sync")
        return None, False

    subscription = await subscription_dao.get_current(user.id)
    if subscription is None:
        logger.warning(
            f"Current local subscription for telegram '{telegram_id}' not found during sync"
        )
        return None, False

    remna_subscription = RemnaSubscriptionDto.from_remna_user(panel_user)
    synced_subscription = remnawave.apply_sync(subscription, remna_subscription)
    changed = bool(synced_subscription.changed_data)
    updated_subscription = await subscription_dao.update(synced_subscription)
    return updated_subscription, changed


async def _sync_linked_devices_subscription_identity(
    panel_user: UserResponseDto,
    device_dao: LinkedDeviceDao,
) -> int:
    telegram_id = _get_panel_user_telegram_id(panel_user)
    if telegram_id is None:
        return 0

    devices = await device_dao.get_by_telegram_id(telegram_id)
    panel_user_uuid = str(panel_user.uuid)
    short_uuid = str(panel_user.short_uuid)

    updated_count = 0
    for device in devices:
        if device.panel_user_uuid == panel_user_uuid and device.short_uuid == short_uuid:
            continue

        await device_dao.upsert(
            replace(
                device,
                panel_user_uuid=panel_user_uuid,
                short_uuid=short_uuid,
            )
        )
        updated_count += 1

    return updated_count


# ── Config endpoint ────────────────────────────────────────────
@router.get("/config")
@inject
async def get_config(
    config: FromDishka[AppConfig],
    plan_dao: FromDishka[PlanDao],
) -> dict:
    trial_plan = await _get_anonymous_trial_plan(plan_dao)
    if not trial_plan:
        return {"success": False, "message": "Trial plan is not configured", "data": None}

    return {
        "success": True,
        "data": _build_trial_config_data(config, trial_plan),
    }


# ── Request / response models ────────────────────────────────────
class AuthRequest(BaseModel):
    device_id: Optional[str] = None
    auth_token: Optional[str] = None
    panel_user_uuid: Optional[str] = None


class DeviceBootstrapRequest(BaseModel):
    device_id: str
    platform: Optional[str] = None
    integrity_token: Optional[str] = None


class DeviceRefreshRequest(BaseModel):
    refresh_token: str


class DeviceRegisterRequest(BaseModel):
    device_id: Optional[str] = None
    telegram_id: Optional[int] = None
    device_name: Optional[str] = None
    device_type: Optional[str] = None
    platform: Optional[str] = None


class DeviceUnlinkRequest(BaseModel):
    device_id: Optional[str] = None
    telegram_id: Optional[int] = None


class TvPairCreateRequest(BaseModel):
    device_id: Optional[str] = None


class TvPairConfirmRequest(BaseModel):
    code: str
    telegram_id: Optional[int] = None


# ── Auth token endpoints ─────────────────────────────────────────
@router.post("/auth/request")
@inject
async def request_auth(
    request: AuthRequest,
    auth: Annotated[DeviceAuthContext, Depends(get_device_auth_context)],
    device_dao: FromDishka[LinkedDeviceDao],
    auth_dao: FromDishka[AuthTokenDao],
    uow: FromDishka[UnitOfWork],
) -> dict:
    device_id = _resolve_device_id(auth, request.device_id)
    auth_token = request.auth_token or secrets.token_urlsafe(24)

    existing = await device_dao.get_by_device_id(device_id)
    if not existing:
        await device_dao.upsert(LinkedDeviceDto(device_id=device_id))

    await auth_dao.create(
        AuthTokenDto(
            token=auth_token,
            device_id=device_id,
            panel_user_uuid=request.panel_user_uuid,
        )
    )
    await uow.commit()

    return {"success": True, "data": {"auth_token": auth_token}}


@router.get("/auth/status")
@inject
async def check_auth_status(
    token: str = Query(...),
    auth_dao: FromDishka[AuthTokenDao] = None,  # type: ignore[assignment]
) -> dict:
    row = await auth_dao.get_by_token(token)
    if not row:
        return {"success": False, "message": "Token not found"}

    if row.status == "completed":
        return {
            "success": True,
            "data": {
                "status": "completed",
                "telegram_id": row.telegram_id,
                "short_uuid": row.short_uuid,
            },
        }

    return {
        "success": True,
        "data": {"status": "pending", "telegram_id": None, "short_uuid": None},
    }


# ── Device management endpoints ──────────────────────────────────
@router.get("/device/traffic")
@inject
async def get_device_traffic(
    auth: Annotated[DeviceAuthContext, Depends(get_device_auth_context)],
    device_id: Optional[str] = Query(default=None),
    device_dao: FromDishka[LinkedDeviceDao] = None,  # type: ignore[assignment]
) -> dict:
    resolved_device_id = _resolve_device_id(auth, device_id)
    device = await device_dao.get_by_device_id(resolved_device_id)
    anon_bytes = device.anon_traffic_bytes if device else 0
    return {"success": True, "data": {"anon_traffic_bytes": anon_bytes or 0}}


@router.post("/device/register")
@inject
async def register_device(
    request: DeviceRegisterRequest,
    auth: Annotated[DeviceAuthContext, Depends(get_device_auth_context)],
    device_dao: FromDishka[LinkedDeviceDao],
    remnawave: FromDishka[Remnawave],
    uow: FromDishka[UnitOfWork],
) -> dict:
    device_id = _resolve_device_id(auth, request.device_id)
    telegram_id = _resolve_telegram_id(auth, request.telegram_id)

    panel_user = await _get_panel_user_by_telegram_id(telegram_id, remnawave)
    if panel_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="telegram_id not authenticated",
        )

    panel_user_uuid = str(panel_user.uuid) if panel_user.uuid else None
    short_uuid = str(panel_user.short_uuid) if panel_user.short_uuid else None
    binding = await bind_linked_device(
        device_dao,
        device_id=device_id,
        telegram_id=telegram_id,
        device_limit=_get_device_limit(panel_user),
        panel_user_uuid=panel_user_uuid,
        short_uuid=short_uuid,
        device_name=request.device_name,
        device_type=request.device_type,
        platform=request.platform or auth.platform,
    )
    if not binding.is_bound:
        return {"success": False, "message": binding.message}

    await uow.commit()

    return {"success": True, "data": None}


@router.post("/device/unlink")
@inject
async def unlink_device(
    request: DeviceUnlinkRequest,
    auth: Annotated[DeviceAuthContext, Depends(get_device_auth_context)],
    device_dao: FromDishka[LinkedDeviceDao],
    session_dao: FromDishka[DeviceSessionDao],
    subscription_dao: FromDishka[SubscriptionDao],
    user_dao: FromDishka[UserDao],
    notifier: FromDishka[Notifier],
    remnawave: FromDishka[Remnawave],
    uow: FromDishka[UnitOfWork],
) -> dict:
    telegram_id = _resolve_telegram_id(auth, request.telegram_id)
    device_id = _resolve_unlink_device_id(auth, request.device_id)

    panel_user = await _get_panel_user_by_telegram_id(telegram_id, remnawave)
    if panel_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="telegram_id not authenticated",
        )

    devices = await remnawave.get_devices(panel_user.uuid)
    if not any(device.hwid == device_id for device in devices):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device is not linked to current Telegram user",
        )

    await device_dao.lock_binding_by_telegram_id(telegram_id)
    linked_device = await device_dao.get_by_device_id(device_id)
    if linked_device and linked_device.telegram_id not in (None, telegram_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device is linked to another Telegram user",
        )

    remaining_devices = await remnawave.delete_device(panel_user.uuid, device_id)
    await device_dao.unlink(device_id, telegram_id)
    await session_dao.revoke(device_id)

    should_reset_subscription_link = device_id != auth.device_id
    revoked_user = (
        await remnawave.revoke_subscription(panel_user.uuid)
        if should_reset_subscription_link
        else None
    )
    updated_subscription = None
    subscription_changed = False
    updated_devices = 0
    subscription_url = None
    notification_sent = False
    if revoked_user is not None:
        subscription_url = revoked_user.subscription_url
        updated_subscription, subscription_changed = await _sync_subscription_from_panel_user(
            revoked_user,
            user_dao,
            subscription_dao,
            remnawave,
        )
        updated_devices = await _sync_linked_devices_subscription_identity(revoked_user, device_dao)

    await uow.commit()

    data = {
        "remaining_devices": remaining_devices,
        "subscription_url": subscription_url,
        "subscription_link_reset": should_reset_subscription_link and revoked_user is not None,
        "bot_subscription_updated": bool(updated_subscription),
        "bot_subscription_changed": subscription_changed,
        "linked_devices_updated": updated_devices,
        "notification_sent": notification_sent,
    }
    if updated_subscription:
        data.update(_build_current_plan_data(updated_subscription))

    if revoked_user is not None:
        user = await user_dao.get_by_telegram_id(telegram_id)
        if user is None:
            logger.warning(
                f"Subscription was reissued during device unlink, but user '{telegram_id}' "
                "was not found for notification"
            )
        else:
            try:
                await notifier.notify_user(
                    user=user,
                    payload=MessagePayloadDto(
                        i18n_key="ntf-devices.subscription-link-reset",
                        i18n_kwargs={
                            "subscription_url": html.escape(subscription_url or "", quote=False)
                        },
                        delete_after=None,
                    ),
                )
                data["notification_sent"] = True
            except Exception as e:
                logger.warning(
                    f"Failed to notify user '{telegram_id}' about subscription reissue: {e}"
                )

    return {"success": True, "data": data}


@router.get("/devices")
@inject
async def get_devices(
    auth: Annotated[DeviceAuthContext, Depends(get_device_auth_context)],
    telegram_id: Optional[int] = Query(default=None),
    remnawave: FromDishka[Remnawave] = None,  # type: ignore[assignment]
) -> dict:
    resolved_telegram_id = _resolve_telegram_id(auth, telegram_id)
    panel_user = await _get_panel_user_by_telegram_id(resolved_telegram_id, remnawave)
    if panel_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="telegram_id not authenticated",
        )

    devices = await remnawave.get_devices(panel_user.uuid)
    return {
        "success": True,
        "data": {
            "current_count": len(devices),
            "max_devices": _get_device_limit(panel_user),
            "devices": [_build_hwid_device_data(device) for device in devices],
        },
    }


# Purchase plans endpoint
@router.get("/purchase/plans")
@inject
async def get_available_purchase_plans(
    auth: Annotated[DeviceAuthContext, Depends(get_device_auth_context)],
    user_dao: FromDishka[UserDao],
    subscription_dao: FromDishka[SubscriptionDao],
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    get_available_plans: FromDishka[GetAvailablePlans],
    match_plan: FromDishka[MatchPlan],
    pricing_service: FromDishka[PricingService],
    bot_service: FromDishka[BotService],
    telegram_id: Optional[int] = Query(default=None),
) -> dict:
    resolved_telegram_id = _resolve_telegram_id(auth, telegram_id)
    user = await user_dao.get_by_telegram_id(resolved_telegram_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    plans = await get_available_plans.system(user)
    current_subscription = await subscription_dao.get_current(user.id)
    gateways = await payment_gateway_dao.get_active()
    renewable_plan_id = None

    if current_subscription and not current_subscription.is_unlimited and plans:
        renewable_plan = await match_plan.system(
            MatchPlanDto(plan_snapshot=current_subscription.plan_snapshot, plans=plans)
        )
        renewable_plan_id = renewable_plan.id if renewable_plan else None

    return {
        "success": True,
        "data": {
            "telegram_id": resolved_telegram_id,
            "effective_discount_percent": pricing_service.get_effective_discount(user),
            "plans": [
                await _build_purchase_plan_data(
                    plan=plan,
                    user=user,
                    current_subscription=current_subscription,
                    renewable_plan_id=renewable_plan_id,
                    gateways=gateways,
                    pricing_service=pricing_service,
                    bot_service=bot_service,
                )
                for plan in sorted(plans, key=lambda item: item.order_index)
            ],
        },
    }


@router.get("/subscription/current-plan")
@inject
async def get_current_subscription_plan(
    auth: Annotated[DeviceAuthContext, Depends(get_device_auth_context)],
    user_dao: FromDishka[UserDao],
    subscription_dao: FromDishka[SubscriptionDao],
    get_available_plans: FromDishka[GetAvailablePlans],
    match_plan: FromDishka[MatchPlan],
    bot_service: FromDishka[BotService],
) -> dict:
    resolved_telegram_id = _resolve_telegram_id(auth, None)
    user = await user_dao.get_by_telegram_id(resolved_telegram_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    current_subscription = await subscription_dao.get_current(user.id)

    if not current_subscription:
        return {
            "success": True,
            "data": {
                "telegram_id": resolved_telegram_id,
                "is_admin": user.is_privileged,
                "renewal_url": None,
                "current_plan": None,
                "subscription": None,
            },
        }

    renewal_url = None
    if not current_subscription.is_unlimited:
        plans = await get_available_plans.system(user)
        renewable_plan = await match_plan.system(
            MatchPlanDto(plan_snapshot=current_subscription.plan_snapshot, plans=plans)
        )
        duration_days = current_subscription.plan_snapshot.duration
        if (
            renewable_plan
            and renewable_plan.id is not None
            and renewable_plan.get_duration(duration_days)
        ):
            renewal_url = await bot_service.get_purchase_url(renewable_plan.id, duration_days)

    return {
        "success": True,
        "data": {
            "telegram_id": resolved_telegram_id,
            "is_admin": user.is_privileged,
            "renewal_url": renewal_url,
            **_build_current_plan_data(current_subscription),
        },
    }


# TV pairing endpoints
@router.post("/tv/pair/create")
@inject
async def tv_pair_create(
    request: TvPairCreateRequest,
    auth: Annotated[DeviceAuthContext, Depends(get_device_auth_context)],
    pairing_dao: FromDishka[TvPairingDao],
    uow: FromDishka[UnitOfWork],
) -> dict:
    device_id = _resolve_device_id(auth, request.device_id)
    code = secrets.token_hex(8).upper()
    await pairing_dao.create(TvPairingCodeDto(code=code, device_id=device_id))
    await uow.commit()

    return {
        "success": True,
        "data": {"code": code, "expires_in": TV_PAIRING_TTL_SECONDS},
    }


@router.post("/tv/pair/confirm")
@inject
async def tv_pair_confirm(
    request: TvPairConfirmRequest,
    auth: Annotated[DeviceAuthContext, Depends(get_device_auth_context)],
    device_dao: FromDishka[LinkedDeviceDao],
    pairing_dao: FromDishka[TvPairingDao],
    remnawave: FromDishka[Remnawave],
    uow: FromDishka[UnitOfWork],
) -> dict:
    telegram_id = _resolve_telegram_id(auth, request.telegram_id)
    # Verify mobile user is authenticated (exists in devices or on panel)
    panel_user = await _get_panel_user_by_telegram_id(telegram_id, remnawave)
    if panel_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="telegram_id not authenticated",
        )

    # Verify code exists, is pending, and not expired
    pairing = await pairing_dao.get_by_code(request.code)
    if pairing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pairing code not found")
    if pairing.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Pairing code already used"
        )
    if pairing.created_at:
        age = (datetime.now(timezone.utc) - pairing.created_at).total_seconds()
        if age > TV_PAIRING_TTL_SECONDS:
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Pairing code expired")

    panel_user_uuid = str(panel_user.uuid) if panel_user.uuid else None
    short_uuid = str(panel_user.short_uuid) if panel_user.short_uuid else None
    if not await pairing_dao.complete(request.code, telegram_id):
        await uow.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pairing code already used",
        )

    binding = await bind_linked_device(
        device_dao,
        device_id=pairing.device_id,
        telegram_id=telegram_id,
        device_limit=_get_device_limit(panel_user),
        panel_user_uuid=panel_user_uuid,
        short_uuid=short_uuid,
    )
    if not binding.is_bound:
        await uow.rollback()
        return {"success": False, "message": binding.message}

    await uow.commit()

    return {"success": True, "data": None}


@router.get("/tv/pair/status")
@inject
async def tv_pair_status(
    code: str = Query(...),
    pairing_dao: FromDishka[TvPairingDao] = None,  # type: ignore[assignment]
    remnawave: FromDishka[Remnawave] = None,  # type: ignore[assignment]
) -> dict:
    pairing = await pairing_dao.get_by_code(code)
    if pairing is None:
        return {"success": False, "message": "Pairing code not found"}

    if pairing.status == "completed":
        panel_user = None
        if pairing.telegram_id is not None:
            try:
                panel_users = await remnawave.get_users_by_telegram_id(pairing.telegram_id)
                if panel_users:
                    panel_user = panel_users[0]
            except Exception:
                logger.warning(f"Failed to fetch panel user for telegram '{pairing.telegram_id}'")

        return {
            "success": True,
            "data": {
                "status": "completed",
                "telegram_id": pairing.telegram_id,
                "short_uuid": (str(panel_user.short_uuid) if panel_user else None),
                "panel_user_uuid": (str(panel_user.uuid) if panel_user else None),
            },
        }

    if pairing.created_at:
        age = (datetime.now(timezone.utc) - pairing.created_at).total_seconds()
        if age > TV_PAIRING_TTL_SECONDS:
            return {
                "success": True,
                "data": {"status": "expired", "telegram_id": None},
            }

    return {
        "success": True,
        "data": {"status": "pending", "telegram_id": None},
    }


# ── Panel proxy endpoints (for mobile/TV — keeps token server-side) ──
@router.get("/panel/user-by-telegram/{telegram_id}")
@inject
async def proxy_user_by_telegram(
    auth: Annotated[DeviceAuthContext, Depends(get_device_auth_context)],
    telegram_id: int,
    remnawave: FromDishka[Remnawave],
) -> dict:
    _resolve_telegram_id(auth, telegram_id)
    try:
        users = await remnawave.get_users_by_telegram_id(telegram_id)
        if not users:
            return {"response": []}
        return {"response": [u.model_dump(mode="json", by_alias=False) for u in users]}
    except Exception as e:
        logger.warning(f"proxy_user_by_telegram failed: {e}")
        return {"response": []}


@router.get("/panel/nodes")
@inject
async def proxy_nodes(
    auth: Annotated[DeviceAuthContext, Depends(get_device_auth_context)],
    remnawave_sdk: FromDishka[RemnawaveSDK],
) -> dict:
    del auth
    try:
        response = await remnawave_sdk.nodes.get_all_nodes()
        return {"response": [n.model_dump(mode="json", by_alias=False) for n in response.root]}
    except Exception as e:
        logger.warning(f"proxy_nodes failed: {e}")
        return {"response": []}


@router.get("/panel/sub/{short_uuid}/info", deprecated=True)
@inject
async def proxy_sub_info(
    auth: Annotated[DeviceAuthContext, Depends(get_device_auth_context)],
    short_uuid: str,
    remnawave_sdk: FromDishka[RemnawaveSDK],
) -> dict:
    _ensure_subscription_short_uuid_access(auth, short_uuid)
    try:
        info = await remnawave_sdk.subscription.get_subscription_info_by_short_uuid(short_uuid)
        if info is None:
            return {
                "response": {
                    "is_found": False,
                    "user": None,
                    "links": None,
                    "subscription_url": None,
                }
            }
        return {"response": info.model_dump(mode="json", by_alias=False)}
    except Exception as e:
        logger.warning(f"proxy_sub_info failed: {e}")
        return {
            "response": {
                "is_found": False,
                "user": None,
                "links": None,
                "subscription_url": None,
            }
        }


# ── Panel subscription management (keeps panel logic server-side) ──
@router.post("/panel/sub/{short_uuid}/revoke", include_in_schema=False)
@router.post("/panel/sub/{short_uuid}/reset")
@inject
async def reset_panel_subscription(
    auth: Annotated[DeviceAuthContext, Depends(get_device_auth_context)],
    short_uuid: str,
    remnawave: FromDishka[Remnawave],
    remnawave_sdk: FromDishka[RemnawaveSDK],
    user_dao: FromDishka[UserDao],
    subscription_dao: FromDishka[SubscriptionDao],
    device_dao: FromDishka[LinkedDeviceDao],
    uow: FromDishka[UnitOfWork],
) -> dict:
    panel_user = await _get_panel_user_for_subscription_action(
        auth=auth,
        short_uuid=short_uuid,
        remnawave=remnawave,
        remnawave_sdk=remnawave_sdk,
    )
    if panel_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Panel user not found")

    revoked_user = await remnawave.revoke_subscription(panel_user.uuid)
    if revoked_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Panel user not found")

    updated_subscription, subscription_changed = await _sync_subscription_from_panel_user(
        revoked_user,
        user_dao,
        subscription_dao,
        remnawave,
    )
    updated_devices = await _sync_linked_devices_subscription_identity(revoked_user, device_dao)
    await uow.commit()

    data = {
        **_build_panel_user_data(revoked_user),
        "subscription_url": revoked_user.subscription_url,
        "bot_subscription_updated": bool(updated_subscription),
        "bot_subscription_changed": subscription_changed,
        "linked_devices_updated": updated_devices,
    }
    if updated_subscription:
        data.update(_build_current_plan_data(updated_subscription))

    return {"success": True, "data": data}


# ── Device user management (keeps panel logic server-side) ────────
class EnsureUserRequest(BaseModel):
    device_id: Optional[str] = None


class SaveEmailRequest(BaseModel):
    panel_user_uuid: Optional[str] = None
    email: EmailStr


@router.post("/device/bootstrap")
@inject
async def bootstrap_device_session(
    request: DeviceBootstrapRequest,
    config: FromDishka[AppConfig],
    cryptographer: FromDishka[Cryptographer],
    session_dao: FromDishka[DeviceSessionDao],
    device_dao: FromDishka[LinkedDeviceDao],
    uow: FromDishka[UnitOfWork],
) -> dict:
    existing_device = await device_dao.get_by_device_id(request.device_id)
    if existing_device is None:
        existing_device = await device_dao.upsert(
            LinkedDeviceDto(device_id=request.device_id, platform=request.platform)
        )
    elif request.platform and request.platform != existing_device.platform:
        existing_device = await device_dao.upsert(
            _merge_linked_device(existing_device, platform=request.platform)
        )

    current_session = await session_dao.get_by_device_id(request.device_id)
    session, access_token, refresh_token = _generate_session_tokens(
        device_id=request.device_id,
        platform=request.platform,
        integrity_token=request.integrity_token,
        config=config,
        cryptographer=cryptographer,
        current_session=current_session,
    )
    await session_dao.upsert(session)
    await uow.commit()

    return {
        "success": True,
        "data": _build_session_response(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=session.access_expires_at,
            refresh_expires_at=session.refresh_expires_at,
            linked_device=existing_device,
        ),
    }


@router.post("/device/refresh")
@inject
async def refresh_device_session(
    request: DeviceRefreshRequest,
    config: FromDishka[AppConfig],
    cryptographer: FromDishka[Cryptographer],
    session_dao: FromDishka[DeviceSessionDao],
    device_dao: FromDishka[LinkedDeviceDao],
    uow: FromDishka[UnitOfWork],
) -> dict:
    refresh_token_hash = cryptographer.get_hash(request.refresh_token)
    current_session = await session_dao.get_by_refresh_token_hash(refresh_token_hash)
    if (
        not current_session
        or current_session.revoked_at
        or _is_expired(current_session.refresh_expires_at)
    ):
        raise _build_device_auth_unauthorized("Invalid or expired refresh token")

    session, access_token, refresh_token = _generate_session_tokens(
        device_id=current_session.device_id,
        platform=current_session.platform,
        integrity_token=None,
        config=config,
        cryptographer=cryptographer,
        current_session=current_session,
    )
    await session_dao.upsert(session)
    linked_device = await device_dao.get_by_device_id(current_session.device_id)
    await uow.commit()

    return {
        "success": True,
        "data": _build_session_response(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=session.access_expires_at,
            refresh_expires_at=session.refresh_expires_at,
            linked_device=linked_device,
        ),
    }


@router.post("/device/logout")
@inject
async def logout_device_session(
    auth: Annotated[DeviceAuthContext, Depends(get_device_auth_context)],
    session_dao: FromDishka[DeviceSessionDao],
    uow: FromDishka[UnitOfWork],
) -> dict:
    if auth.device_id:
        await session_dao.revoke(auth.device_id)
        await uow.commit()

    return {"success": True, "data": None}


@router.post("/device/ensure-user")
@inject
async def ensure_user(  # noqa: C901
    request: EnsureUserRequest,
    auth: Annotated[DeviceAuthContext, Depends(get_device_auth_context)],
    config: FromDishka[AppConfig],
    plan_dao: FromDishka[PlanDao],
    device_dao: FromDishka[LinkedDeviceDao],
    remnawave: FromDishka[Remnawave],
    remnawave_sdk: FromDishka[RemnawaveSDK],
) -> dict:
    """Find or create an anonymous panel user for a device."""
    device_id = _resolve_device_id(auth, request.device_id)
    username = _build_device_username(device_id)
    linked_device = await device_dao.get_by_device_id(device_id)
    saved_anon_traffic = _get_saved_anon_traffic(linked_device)

    if _is_linked_device_bound(linked_device):
        linked_user = None
        if linked_device and linked_device.panel_user_uuid:
            linked_user = await remnawave.get_user_by_uuid(linked_device.panel_user_uuid)
        if not linked_user and linked_device and linked_device.telegram_id is not None:
            linked_user = await _get_panel_user_by_telegram_id(
                linked_device.telegram_id,
                remnawave,
            )
        if not linked_user:
            return {
                "success": False,
                "message": "Device is linked but panel user was not found",
            }

        return {
            "success": True,
            "data": _build_panel_user_data(
                linked_user,
                anon_traffic_bytes=saved_anon_traffic,
                is_anonymous=False,
            ),
        }

    # Try to find existing user
    try:
        user = await _get_anonymous_panel_user_by_device_id(device_id, remnawave_sdk)
        if user:
            try:
                await _ensure_panel_user_device_comment(
                    remnawave_sdk,
                    user,
                    device_id,
                    saved_anon_traffic,
                )
            except Exception as e:
                logger.warning(f"ensure_user failed to save device_id comment: {e}")
            return {
                "success": True,
                "data": _build_panel_user_data(
                    user,
                    extra_traffic_used_bytes=saved_anon_traffic,
                    is_anonymous=True,
                ),
            }
    except Exception as e:
        logger.warning(f"ensure_user lookup failed: {e}")

    trial_plan = await _get_anonymous_trial_plan(plan_dao)
    if not trial_plan:
        return {"success": False, "message": "Trial plan is not configured"}

    duration_days = _get_plan_duration_days(trial_plan)
    if duration_days is None:
        logger.warning(f"ToBeVPN trial plan '{trial_plan.id}' has no durations")
        return {"success": False, "message": "Trial plan is not configured"}

    traffic_limit_bytes = _get_anonymous_trial_traffic_limit_bytes(config, trial_plan)
    effective_traffic_limit_bytes = _get_effective_anonymous_trial_traffic_limit_bytes(
        traffic_limit_bytes,
        saved_anon_traffic,
    )

    # Create an anonymous user with the trial plan metadata and remaining free limit.
    try:
        user = await remnawave_sdk.users.create_user(
            CreateUserRequestDto(
                username=username,
                traffic_limit_bytes=effective_traffic_limit_bytes,
                traffic_limit_strategy=trial_plan.traffic_limit_strategy,
                expire_at=days_to_datetime(duration_days),
                hwid_device_limit=trial_plan.device_limit,
                active_internal_squads=trial_plan.internal_squads,
                external_squad_uuid=trial_plan.external_squad,
                tag=trial_plan.tag,
                description=_build_anonymous_description(
                    trial_plan,
                    device_id,
                    saved_anon_traffic,
                ),
            )
        )
        return {
            "success": True,
            "data": _build_panel_user_data(
                user,
                extra_traffic_used_bytes=saved_anon_traffic,
                traffic_limit_bytes=traffic_limit_bytes,
                trial_plan_id=trial_plan.id,
                is_anonymous=True,
            ),
        }
    except ConflictError:
        # Race condition — user was created between lookup and create
        try:
            user = await remnawave_sdk.users.get_user_by_username(username)
            try:
                await _ensure_panel_user_device_comment(
                    remnawave_sdk,
                    user,
                    device_id,
                    saved_anon_traffic,
                )
            except Exception as e:
                logger.warning(f"ensure_user failed to save device_id comment: {e}")
            return {
                "success": True,
                "data": _build_panel_user_data(
                    user,
                    extra_traffic_used_bytes=saved_anon_traffic,
                    is_anonymous=True,
                ),
            }
        except Exception as e:
            logger.error(f"ensure_user re-lookup after conflict failed: {e}")
            return {"success": False, "message": "Failed to create user"}
    except Exception as e:
        logger.error(f"ensure_user create failed: {e}")
        return {"success": False, "message": "Failed to create user"}


@router.post("/device/save-email")
@inject
async def save_email(
    request: SaveEmailRequest,
    auth: Annotated[DeviceAuthContext, Depends(get_device_auth_context)],
    device_dao: FromDishka[LinkedDeviceDao],
    remnawave: FromDishka[Remnawave],
    remnawave_sdk: FromDishka[RemnawaveSDK],
) -> dict:
    """Update email on a panel user."""
    panel_user_uuid = auth.panel_user_uuid
    if auth.device_id and panel_user_uuid is None:
        linked_device = await device_dao.get_by_device_id(auth.device_id)
        if linked_device and linked_device.panel_user_uuid:
            panel_user_uuid = linked_device.panel_user_uuid
        elif linked_device and linked_device.telegram_id is not None:
            linked_user = await _get_panel_user_by_telegram_id(linked_device.telegram_id, remnawave)
            panel_user_uuid = str(linked_user.uuid) if linked_user else None

    if panel_user_uuid is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current device session is not linked to a panel user",
        )

    if request.panel_user_uuid is not None and request.panel_user_uuid != panel_user_uuid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="panel_user_uuid does not match current device session",
        )
    resolved_panel_user_uuid = panel_user_uuid
    try:
        await remnawave_sdk.users.update_user(
            UpdateUserRequestDto(
                uuid=resolved_panel_user_uuid,
                email=request.email,
            )
        )
        return {"success": True, "data": None}
    except NotFoundError:
        return {"success": False, "message": "User not found"}
    except Exception as e:
        logger.error(f"save_email failed: {e}")
        return {"success": False, "message": "Failed to save email"}
