"""
ToBeVPN device management, auth-token flow, TV pairing, and panel proxy endpoints.

These endpoints are consumed by the Android/TV client apps and keep
sensitive credentials (Remnawave API token) server-side.
"""

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel, EmailStr
from remnapy import RemnawaveSDK
from remnapy.exceptions import ConflictError, NotFoundError
from remnapy.models import CreateUserRequestDto, UpdateUserRequestDto, UserResponseDto

from src.application.common import Remnawave
from src.application.common.dao import AuthTokenDao, LinkedDeviceDao, PlanDao, TvPairingDao
from src.application.common.uow import UnitOfWork
from src.application.dto import PlanDto
from src.application.dto.device import AuthTokenDto, LinkedDeviceDto, TvPairingCodeDto
from src.core.constants import TV_PAIRING_TTL_SECONDS
from src.core.enums import PlanAvailability
from src.core.utils.converters import days_to_datetime, gb_to_bytes

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
    logger.info(
        f"Selected ToBeVPN trial plan '{plan.id}' with availability '{plan.availability}'"
    )
    return plan


def _build_trial_config_data(plan: PlanDto) -> dict:
    duration_days = _get_plan_duration_days(plan)
    internal_squad_uuids = [str(uuid) for uuid in plan.internal_squads]

    return {
        "trial_plan_id": plan.id,
        "trial_plan_name": plan.name,
        "free_squad_uuid": internal_squad_uuids[0] if internal_squad_uuids else None,
        "free_squad_uuids": internal_squad_uuids,
        "external_squad_uuid": str(plan.external_squad) if plan.external_squad else None,
        "free_trial_traffic_bytes": gb_to_bytes(plan.traffic_limit),
        "free_trial_days": duration_days,
    }


def _build_device_username(device_id: str) -> str:
    digest = hashlib.sha256(device_id.encode()).hexdigest()[:32]
    return f"app_{digest}"


async def _get_panel_user_by_telegram_id(
    telegram_id: int,
    remnawave: Remnawave,
) -> Optional[UserResponseDto]:
    panel_users = await remnawave.get_user_by_telegram_id(telegram_id)
    return panel_users[0] if panel_users else None


def _get_device_limit(panel_user: UserResponseDto) -> int:
    return panel_user.hwid_device_limit or 0


def _is_device_limit_reached(linked_count: int, device_limit: int) -> bool:
    return device_limit > 0 and linked_count >= device_limit


# ── Config endpoint ────────────────────────────────────────────
@router.get("/config")
@inject
async def get_config(plan_dao: FromDishka[PlanDao]) -> dict:
    trial_plan = await _get_anonymous_trial_plan(plan_dao)
    if not trial_plan:
        return {"success": False, "message": "Trial plan is not configured", "data": None}

    return {
        "success": True,
        "data": _build_trial_config_data(trial_plan),
    }


# ── Request / response models ────────────────────────────────────
class AuthRequest(BaseModel):
    device_id: str
    auth_token: str
    panel_user_uuid: Optional[str] = None


class DeviceRegisterRequest(BaseModel):
    device_id: str
    telegram_id: int
    device_name: Optional[str] = None
    device_type: Optional[str] = None
    platform: Optional[str] = None


class DeviceUnlinkRequest(BaseModel):
    device_id: str
    telegram_id: int


class TvPairCreateRequest(BaseModel):
    device_id: str


class TvPairConfirmRequest(BaseModel):
    code: str
    telegram_id: int


# ── Auth token endpoints ─────────────────────────────────────────
@router.post("/auth/request")
@inject
async def request_auth(
    request: AuthRequest,
    device_dao: FromDishka[LinkedDeviceDao],
    auth_dao: FromDishka[AuthTokenDao],
    uow: FromDishka[UnitOfWork],
) -> dict:
    existing = await device_dao.get_by_device_id(request.device_id)
    if not existing:
        await device_dao.upsert(LinkedDeviceDto(device_id=request.device_id))

    await auth_dao.create(
        AuthTokenDto(
            token=request.auth_token,
            device_id=request.device_id,
            panel_user_uuid=request.panel_user_uuid,
        )
    )
    await uow.commit()

    return {"success": True, "data": None}


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
    device_id: str = Query(...),
    device_dao: FromDishka[LinkedDeviceDao] = None,  # type: ignore[assignment]
) -> dict:
    device = await device_dao.get_by_device_id(device_id)
    anon_bytes = device.anon_traffic_bytes if device else 0
    return {"success": True, "data": {"anon_traffic_bytes": anon_bytes or 0}}


@router.post("/device/register")
@inject
async def register_device(
    request: DeviceRegisterRequest,
    device_dao: FromDishka[LinkedDeviceDao],
    remnawave: FromDishka[Remnawave],
    uow: FromDishka[UnitOfWork],
) -> dict:
    panel_user = await _get_panel_user_by_telegram_id(request.telegram_id, remnawave)
    if panel_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="telegram_id not authenticated",
        )

    device_limit = _get_device_limit(panel_user)

    existing = await device_dao.get_by_device_id(request.device_id)
    already_linked = existing is not None and existing.telegram_id == request.telegram_id

    if not already_linked:
        linked_count = await device_dao.count_by_telegram_id(
            request.telegram_id,
            exclude_device_id=request.device_id,
        )
        if _is_device_limit_reached(linked_count, device_limit):
            return {
                "success": False,
                "message": f"Device limit reached. Maximum is {device_limit}.",
            }

    await device_dao.upsert(
        LinkedDeviceDto(
            device_id=request.device_id,
            telegram_id=request.telegram_id,
            device_name=request.device_name,
            device_type=request.device_type,
            platform=request.platform,
        )
    )
    await uow.commit()

    return {"success": True, "data": None}


@router.post("/device/unlink")
@inject
async def unlink_device(
    request: DeviceUnlinkRequest,
    device_dao: FromDishka[LinkedDeviceDao],
    uow: FromDishka[UnitOfWork],
) -> dict:
    await device_dao.unlink(request.device_id, request.telegram_id)
    await uow.commit()
    return {"success": True, "data": None}


@router.get("/devices")
@inject
async def get_devices(
    telegram_id: int = Query(...),
    device_dao: FromDishka[LinkedDeviceDao] = None,  # type: ignore[assignment]
    remnawave: FromDishka[Remnawave] = None,  # type: ignore[assignment]
) -> dict:
    panel_user = await _get_panel_user_by_telegram_id(telegram_id, remnawave)
    if panel_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="telegram_id not authenticated",
        )

    devices = await device_dao.get_by_telegram_id(telegram_id)
    return {
        "success": True,
        "data": {
            "max_devices": _get_device_limit(panel_user),
            "devices": [
                {
                    "device_id": d.device_id,
                    "device_name": d.device_name,
                    "device_type": d.device_type,
                    "platform": d.platform,
                    "linked_at": (int(d.created_at.timestamp()) if d.created_at else None),
                    "last_seen_at": (int(d.updated_at.timestamp()) if d.updated_at else None),
                }
                for d in devices
            ],
        },
    }


# ── TV pairing endpoints ─────────────────────────────────────────
@router.post("/tv/pair/create")
@inject
async def tv_pair_create(
    request: TvPairCreateRequest,
    pairing_dao: FromDishka[TvPairingDao],
    uow: FromDishka[UnitOfWork],
) -> dict:
    code = secrets.token_hex(8).upper()
    await pairing_dao.create(TvPairingCodeDto(code=code, device_id=request.device_id))
    await uow.commit()

    return {
        "success": True,
        "data": {"code": code, "expires_in": TV_PAIRING_TTL_SECONDS},
    }


@router.post("/tv/pair/confirm")
@inject
async def tv_pair_confirm(
    request: TvPairConfirmRequest,
    device_dao: FromDishka[LinkedDeviceDao],
    pairing_dao: FromDishka[TvPairingDao],
    remnawave: FromDishka[Remnawave],
    uow: FromDishka[UnitOfWork],
) -> dict:
    # Verify mobile user is authenticated (exists in devices or on panel)
    panel_user = await _get_panel_user_by_telegram_id(request.telegram_id, remnawave)
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

    # Check device limit
    device_limit = _get_device_limit(panel_user)
    linked_count = await device_dao.count_by_telegram_id(request.telegram_id)
    if _is_device_limit_reached(linked_count, device_limit):
        return {
            "success": False,
            "message": f"Device limit reached. Maximum is {device_limit}.",
        }

    await pairing_dao.complete(request.code, request.telegram_id)
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
                panel_users = await remnawave.get_user_by_telegram_id(pairing.telegram_id)
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
    telegram_id: int,
    remnawave: FromDishka[Remnawave],
) -> dict:
    try:
        users = await remnawave.get_user_by_telegram_id(telegram_id)
        if not users:
            return {"response": []}
        return {"response": [u.model_dump(mode="json") for u in users]}
    except Exception as e:
        logger.warning(f"proxy_user_by_telegram failed: {e}")
        return {"response": []}


@router.get("/panel/nodes")
@inject
async def proxy_nodes(
    remnawave_sdk: FromDishka[RemnawaveSDK],
) -> dict:
    try:
        response = await remnawave_sdk.nodes.get_all_nodes()
        return {"response": [n.model_dump(mode="json") for n in response.root]}
    except Exception as e:
        logger.warning(f"proxy_nodes failed: {e}")
        return {"response": []}


@router.get("/panel/sub/{short_uuid}/info")
@inject
async def proxy_sub_info(
    short_uuid: str,
    remnawave_sdk: FromDishka[RemnawaveSDK],
) -> dict:
    try:
        info = await remnawave_sdk.subscription.get_subscription_info_by_short_uuid(short_uuid)
        if info is None:
            return {
                "response": {
                    "isFound": False,
                    "user": None,
                    "links": None,
                    "subscriptionUrl": None,
                }
            }
        return {"response": info.model_dump(mode="json")}
    except Exception as e:
        logger.warning(f"proxy_sub_info failed: {e}")
        return {
            "response": {
                "isFound": False,
                "user": None,
                "links": None,
                "subscriptionUrl": None,
            }
        }


# ── Device user management (keeps panel logic server-side) ────────
class EnsureUserRequest(BaseModel):
    device_id: str


class SaveEmailRequest(BaseModel):
    panel_user_uuid: str
    email: EmailStr


@router.post("/device/ensure-user")
@inject
async def ensure_user(
    request: EnsureUserRequest,
    plan_dao: FromDishka[PlanDao],
    remnawave_sdk: FromDishka[RemnawaveSDK],
) -> dict:
    """Find or create an anonymous panel user for a device."""
    username = _build_device_username(request.device_id)

    # Try to find existing user
    try:
        user = await remnawave_sdk.users.get_user_by_username(username)
        traffic_used = 0
        if user.used_traffic_bytes is not None:
            traffic_used = user.used_traffic_bytes
        return {
            "success": True,
            "data": {
                "short_uuid": str(user.short_uuid),
                "panel_user_uuid": str(user.uuid),
                "traffic_limit_bytes": user.traffic_limit_bytes or 0,
                "traffic_used_bytes": traffic_used,
                "max_devices": user.hwid_device_limit or 0,
            },
        }
    except NotFoundError:
        pass
    except Exception as e:
        logger.warning(f"ensure_user lookup failed: {e}")

    trial_plan = await _get_anonymous_trial_plan(plan_dao)
    if not trial_plan:
        return {"success": False, "message": "Trial plan is not configured"}

    duration_days = _get_plan_duration_days(trial_plan)
    if duration_days is None:
        logger.warning(f"ToBeVPN trial plan '{trial_plan.id}' has no durations")
        return {"success": False, "message": "Trial plan is not configured"}

    traffic_limit_bytes = gb_to_bytes(trial_plan.traffic_limit)

    # Create new anonymous user with the same trial plan fields as the bot flow.
    try:
        user = await remnawave_sdk.users.create_user(
            CreateUserRequestDto(
                username=username,
                traffic_limit_bytes=traffic_limit_bytes,
                traffic_limit_strategy=trial_plan.traffic_limit_strategy,
                expire_at=days_to_datetime(duration_days),
                hwid_device_limit=trial_plan.device_limit,
                active_internal_squads=trial_plan.internal_squads,
                external_squad_uuid=trial_plan.external_squad,
                tag=trial_plan.tag,
                description=trial_plan.description or f"ToBeVPN trial: {trial_plan.name}",
            )
        )
        return {
            "success": True,
            "data": {
                "short_uuid": str(user.short_uuid),
                "panel_user_uuid": str(user.uuid),
                "traffic_limit_bytes": traffic_limit_bytes,
                "traffic_used_bytes": 0,
                "trial_plan_id": trial_plan.id,
                "max_devices": user.hwid_device_limit or 0,
            },
        }
    except ConflictError:
        # Race condition — user was created between lookup and create
        try:
            user = await remnawave_sdk.users.get_user_by_username(username)
            traffic_used = 0
            if user.used_traffic_bytes is not None:
                traffic_used = user.used_traffic_bytes
            return {
                "success": True,
                "data": {
                    "short_uuid": str(user.short_uuid),
                    "panel_user_uuid": str(user.uuid),
                    "traffic_limit_bytes": user.traffic_limit_bytes or 0,
                    "traffic_used_bytes": traffic_used,
                    "max_devices": user.hwid_device_limit or 0,
                },
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
    remnawave_sdk: FromDishka[RemnawaveSDK],
) -> dict:
    """Update email on a panel user."""
    try:
        await remnawave_sdk.users.update_user(
            UpdateUserRequestDto(
                uuid=request.panel_user_uuid,
                email=request.email,
            )
        )
        return {"success": True, "data": None}
    except NotFoundError:
        return {"success": False, "message": "User not found"}
    except Exception as e:
        logger.error(f"save_email failed: {e}")
        return {"success": False, "message": "Failed to save email"}
