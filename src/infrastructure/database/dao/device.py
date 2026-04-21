from datetime import datetime, timedelta, timezone
from typing import Optional, cast

from adaptix import Retort
from adaptix.conversion import ConversionRetort
from loguru import logger
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.common.dao.device import (
    AuthTokenDao,
    DeviceSessionDao,
    LinkedDeviceDao,
    TvPairingDao,
)
from src.application.dto.device import (
    AuthTokenDto,
    DeviceSessionDto,
    LinkedDeviceDto,
    TvPairingCodeDto,
)
from src.infrastructure.database.models import AuthToken, DeviceSession, LinkedDevice, TvPairingCode


class LinkedDeviceDaoImpl(LinkedDeviceDao):
    def __init__(
        self,
        session: AsyncSession,
        retort: Retort,
        conversion_retort: ConversionRetort,
    ) -> None:
        self.session = session
        self.retort = retort
        self.conversion_retort = conversion_retort
        self._to_dto = self.conversion_retort.get_converter(LinkedDevice, LinkedDeviceDto)
        self._to_dto_list = self.conversion_retort.get_converter(
            list[LinkedDevice], list[LinkedDeviceDto]
        )

    async def upsert(self, device: LinkedDeviceDto) -> LinkedDeviceDto:
        data = self.retort.dump(device)
        data.pop("id", None)
        data.pop("created_at", None)
        data.pop("updated_at", None)

        stmt = (
            pg_insert(LinkedDevice)
            .values(**data)
            .on_conflict_do_update(
                index_elements=[LinkedDevice.device_id],
                set_={
                    "telegram_id": data.get("telegram_id"),
                    "panel_user_uuid": data.get("panel_user_uuid"),
                    "short_uuid": data.get("short_uuid"),
                    "device_name": data.get("device_name"),
                    "device_type": data.get("device_type"),
                    "platform": data.get("platform"),
                },
            )
            .returning(LinkedDevice)
        )
        db_device = await self.session.scalar(stmt)
        await self.session.flush()

        logger.debug(f"Upserted device '{device.device_id}'")
        return self._to_dto(db_device)

    async def get_by_device_id(self, device_id: str) -> Optional[LinkedDeviceDto]:
        stmt = select(LinkedDevice).where(LinkedDevice.device_id == device_id)
        db_device = await self.session.scalar(stmt)
        if db_device:
            return self._to_dto(db_device)
        return None

    async def get_by_telegram_id(self, telegram_id: int) -> list[LinkedDeviceDto]:
        stmt = (
            select(LinkedDevice)
            .where(LinkedDevice.telegram_id == telegram_id)
            .order_by(LinkedDevice.updated_at.desc())
        )
        result = await self.session.scalars(stmt)
        db_devices = cast(list, result.all())
        return self._to_dto_list(db_devices)

    async def count_by_telegram_id(
        self, telegram_id: int, exclude_device_id: Optional[str] = None
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(LinkedDevice)
            .where(LinkedDevice.telegram_id == telegram_id)
        )
        if exclude_device_id:
            stmt = stmt.where(LinkedDevice.device_id != exclude_device_id)
        count = await self.session.scalar(stmt) or 0
        return count

    async def unlink(self, device_id: str, telegram_id: int) -> bool:
        stmt = (
            update(LinkedDevice)
            .where(
                LinkedDevice.device_id == device_id,
                LinkedDevice.telegram_id == telegram_id,
            )
            .values(
                telegram_id=None,
                panel_user_uuid=None,
                short_uuid=None,
            )
            .returning(LinkedDevice.id)
        )
        result = await self.session.scalar(stmt)
        if result:
            logger.debug(f"Unlinked device '{device_id}' from telegram '{telegram_id}'")
            return True
        return False

    async def add_anon_traffic(self, device_id: str, traffic_bytes: int) -> None:
        stmt = (
            update(LinkedDevice)
            .where(LinkedDevice.device_id == device_id)
            .values(
                anon_traffic_bytes=func.coalesce(LinkedDevice.anon_traffic_bytes, 0)
                + traffic_bytes
            )
        )
        await self.session.execute(stmt)
        logger.debug(f"Added {traffic_bytes} anon traffic bytes to device '{device_id}'")


class AuthTokenDaoImpl(AuthTokenDao):
    def __init__(
        self,
        session: AsyncSession,
        retort: Retort,
        conversion_retort: ConversionRetort,
    ) -> None:
        self.session = session
        self.retort = retort
        self.conversion_retort = conversion_retort
        self._to_dto = self.conversion_retort.get_converter(AuthToken, AuthTokenDto)

    async def create(self, auth_token: AuthTokenDto) -> AuthTokenDto:
        data = self.retort.dump(auth_token)
        data.pop("id", None)
        data.pop("created_at", None)
        data.pop("updated_at", None)

        stmt = (
            pg_insert(AuthToken)
            .values(**data)
            .on_conflict_do_update(
                index_elements=[AuthToken.token],
                set_={
                    "device_id": data["device_id"],
                    "status": "pending",
                    "panel_user_uuid": data.get("panel_user_uuid"),
                },
            )
            .returning(AuthToken)
        )
        db_token = await self.session.scalar(stmt)
        await self.session.flush()

        logger.debug(f"Created/updated auth token for device '{auth_token.device_id}'")
        return self._to_dto(db_token)

    async def get_by_token(self, token: str) -> Optional[AuthTokenDto]:
        stmt = select(AuthToken).where(AuthToken.token == token)
        db_token = await self.session.scalar(stmt)
        if db_token:
            return self._to_dto(db_token)
        return None

    async def complete(
        self,
        token: str,
        telegram_id: int,
        short_uuid: Optional[str] = None,
    ) -> bool:
        stmt = (
            update(AuthToken)
            .where(AuthToken.token == token)
            .values(status="completed", telegram_id=telegram_id, short_uuid=short_uuid)
            .returning(AuthToken.id)
        )
        result = await self.session.scalar(stmt)
        if result:
            logger.debug(f"Auth token completed for telegram '{telegram_id}'")
            return True
        return False

    async def cleanup_expired(self, max_age_seconds: int = 86400) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        stmt = (
            delete(AuthToken)
            .where(AuthToken.created_at < cutoff, AuthToken.status == "pending")
            .returning(AuthToken.id)
        )
        result = await self.session.execute(stmt)
        count = len(result.all())
        if count:
            logger.debug(f"Cleaned up {count} expired auth tokens")
        return count


class DeviceSessionDaoImpl(DeviceSessionDao):
    def __init__(
        self,
        session: AsyncSession,
        retort: Retort,
        conversion_retort: ConversionRetort,
    ) -> None:
        self.session = session
        self.retort = retort
        self.conversion_retort = conversion_retort
        self._to_dto = self.conversion_retort.get_converter(DeviceSession, DeviceSessionDto)

    async def upsert(self, session: DeviceSessionDto) -> DeviceSessionDto:
        data = self.retort.dump(session)
        data.pop("id", None)
        data.pop("created_at", None)
        data.pop("updated_at", None)

        stmt = (
            pg_insert(DeviceSession)
            .values(**data)
            .on_conflict_do_update(
                index_elements=[DeviceSession.device_id],
                set_={
                    "access_token_hash": data["access_token_hash"],
                    "refresh_token_hash": data["refresh_token_hash"],
                    "access_expires_at": data["access_expires_at"],
                    "refresh_expires_at": data["refresh_expires_at"],
                    "platform": data.get("platform"),
                    "integrity_token_hash": data.get("integrity_token_hash"),
                    "last_used_at": data.get("last_used_at"),
                    "revoked_at": data.get("revoked_at"),
                },
            )
            .returning(DeviceSession)
        )
        db_session = await self.session.scalar(stmt)
        await self.session.flush()

        logger.debug(f"Upserted device session for '{session.device_id}'")
        return self._to_dto(db_session)

    async def get_by_device_id(self, device_id: str) -> Optional[DeviceSessionDto]:
        stmt = select(DeviceSession).where(DeviceSession.device_id == device_id)
        db_session = await self.session.scalar(stmt)
        if db_session:
            return self._to_dto(db_session)
        return None

    async def get_by_access_token_hash(self, token_hash: str) -> Optional[DeviceSessionDto]:
        stmt = select(DeviceSession).where(DeviceSession.access_token_hash == token_hash)
        db_session = await self.session.scalar(stmt)
        if db_session:
            return self._to_dto(db_session)
        return None

    async def get_by_refresh_token_hash(self, token_hash: str) -> Optional[DeviceSessionDto]:
        stmt = select(DeviceSession).where(DeviceSession.refresh_token_hash == token_hash)
        db_session = await self.session.scalar(stmt)
        if db_session:
            return self._to_dto(db_session)
        return None

    async def revoke(self, device_id: str) -> bool:
        stmt = (
            update(DeviceSession)
            .where(DeviceSession.device_id == device_id, DeviceSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
            .returning(DeviceSession.id)
        )
        result = await self.session.scalar(stmt)
        if result:
            logger.debug(f"Revoked device session for '{device_id}'")
            return True
        return False

    async def touch(self, device_id: str) -> None:
        stmt = (
            update(DeviceSession)
            .where(DeviceSession.device_id == device_id)
            .values(last_used_at=datetime.now(timezone.utc))
        )
        await self.session.execute(stmt)

    async def cleanup_expired(self) -> int:
        now = datetime.now(timezone.utc)
        stmt = (
            delete(DeviceSession)
            .where(
                DeviceSession.refresh_expires_at < now,
            )
            .returning(DeviceSession.id)
        )
        result = await self.session.execute(stmt)
        count = len(result.all())
        if count:
            logger.debug(f"Cleaned up {count} expired device sessions")
        return count


class TvPairingDaoImpl(TvPairingDao):
    def __init__(
        self,
        session: AsyncSession,
        retort: Retort,
        conversion_retort: ConversionRetort,
    ) -> None:
        self.session = session
        self.retort = retort
        self.conversion_retort = conversion_retort
        self._to_dto = self.conversion_retort.get_converter(TvPairingCode, TvPairingCodeDto)

    async def create(self, pairing: TvPairingCodeDto) -> TvPairingCodeDto:
        data = self.retort.dump(pairing)
        data.pop("id", None)
        data.pop("created_at", None)
        data.pop("updated_at", None)

        db_pairing = TvPairingCode(**data)
        self.session.add(db_pairing)
        await self.session.flush()

        logger.debug(f"Created TV pairing code '{pairing.code}' for device '{pairing.device_id}'")
        return self._to_dto(db_pairing)

    async def get_by_code(self, code: str) -> Optional[TvPairingCodeDto]:
        stmt = select(TvPairingCode).where(TvPairingCode.code == code)
        db_pairing = await self.session.scalar(stmt)
        if db_pairing:
            return self._to_dto(db_pairing)
        return None

    async def complete(self, code: str, telegram_id: int) -> bool:
        stmt = (
            update(TvPairingCode)
            .where(TvPairingCode.code == code)
            .values(status="completed", telegram_id=telegram_id)
            .returning(TvPairingCode.id)
        )
        result = await self.session.scalar(stmt)
        if result:
            logger.debug(f"TV pairing code '{code}' completed for telegram '{telegram_id}'")
            return True
        return False

    async def cleanup_expired(
        self, ttl_seconds: int = 300, completed_grace_seconds: int = 600
    ) -> int:
        now = datetime.now(timezone.utc)
        pending_cutoff = now - timedelta(seconds=ttl_seconds)
        completed_cutoff = now - timedelta(seconds=ttl_seconds + completed_grace_seconds)

        stmt_pending = (
            delete(TvPairingCode)
            .where(TvPairingCode.created_at < pending_cutoff, TvPairingCode.status == "pending")
            .returning(TvPairingCode.id)
        )
        stmt_completed = (
            delete(TvPairingCode)
            .where(
                TvPairingCode.created_at < completed_cutoff,
                TvPairingCode.status == "completed",
            )
            .returning(TvPairingCode.id)
        )

        r1 = await self.session.execute(stmt_pending)
        r2 = await self.session.execute(stmt_completed)
        count = len(r1.all()) + len(r2.all())
        if count:
            logger.debug(f"Cleaned up {count} expired TV pairing codes")
        return count
