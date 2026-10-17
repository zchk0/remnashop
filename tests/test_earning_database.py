"""Set EARNING_TEST_DATABASE_URL to an isolated PostgreSQL database to run these checks."""

import asyncio
import importlib
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.enums import ChatMemberStatus
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.application.dto import SettingsDto, UserDto
from src.application.dto.earning import ChannelClaimDto, ChannelTaskDto, EarningSettingsDto
from src.application.use_cases.earning.rewards import ClaimChannelReward, EarningError
from src.infrastructure.database.dao.earning import EarningDaoImpl
from src.infrastructure.database.models.earning import ChannelClaim
from src.infrastructure.database.uow import UnitOfWorkImpl
from src.infrastructure.di.providers.retort import RetortProvider


@pytest.fixture
async def earning_database():
    dsn = os.environ.get("EARNING_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("EARNING_TEST_DATABASE_URL is not configured")
    schema = "earning_test_" + uuid4().hex
    base_engine = create_async_engine(dsn)
    async with base_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(dsn, connect_args={"server_settings": {"search_path": schema}})
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0052_add_channel_earning"
    )
    completion_migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0053_add_channel_claim_completed_at"
    )

    def upgrade(connection):
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            completion_migration.upgrade()

    try:
        async with engine.begin() as connection:
            for table in ("users", "plans", "settings"):
                await connection.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
            await connection.execute(text("INSERT INTO users VALUES (1), (2)"))
            await connection.execute(text("INSERT INTO settings VALUES (1)"))
            await connection.run_sync(upgrade)
        yield engine
    finally:
        await engine.dispose()
        async with base_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await base_engine.dispose()


async def seed_task(engine, *, max_claims=None):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        dao = EarningDaoImpl(session)
        task = await dao.save_task(
            ChannelTaskDto(
                title="Test",
                channel_id=-1001234567890,
                channel_url="https://t.me/test",
                days=0,
                discount=15,
                active=True,
                max_claims=max_claims,
            )
        )
        await session.commit()
        return task


async def claim(engine, task_id, user_id, *, publish=None):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        actor = UserDto(id=user_id, telegram_id=100 + user_id, name="Test")

        async def member(*args):
            await asyncio.sleep(0.03)
            return SimpleNamespace(status=ChatMemberStatus.MEMBER)

        service = ClaimChannelReward(
            EarningDaoImpl(session),
            SimpleNamespace(
                get=AsyncMock(
                    return_value=SettingsDto(
                        earning=EarningSettingsDto(enabled=True, audience="all"),
                    )
                )
            ),
            SimpleNamespace(get_by_id=AsyncMock(return_value=replace(actor)), update=AsyncMock()),
            SimpleNamespace(get_current=AsyncMock(return_value=None)),
            SimpleNamespace(),
            SimpleNamespace(get_chat_member=member),
            SimpleNamespace(),
            RetortProvider().get_retort(),
            UnitOfWorkImpl(session),
            SimpleNamespace(publish=publish or AsyncMock()),
        )
        try:
            await service(actor, task_id)
            return "completed"
        except EarningError as error:
            return str(error)


async def test_postgres_last_slot_cannot_be_claimed_twice(earning_database):
    task = await seed_task(earning_database, max_claims=1)
    publish = AsyncMock()
    results = await asyncio.gather(
        claim(earning_database, task.id, 1, publish=publish),
        claim(earning_database, task.id, 2, publish=publish),
    )
    assert sorted(results) == ["completed", "ntf-earning.full"]
    publish.assert_awaited_once()
    assert publish.await_args.args[0].task_id == task.id
    async with AsyncSession(earning_database) as session:
        stored = await EarningDaoImpl(session).get_task(task.id)
        assert stored.claims_count == 1


async def test_postgres_double_click_has_one_ledger_entry(earning_database):
    task = await seed_task(earning_database)
    publish = AsyncMock()
    results = await asyncio.gather(
        claim(earning_database, task.id, 1, publish=publish),
        claim(earning_database, task.id, 1, publish=publish),
    )
    assert sorted(results) == ["completed", "ntf-earning.already-claimed"]
    publish.assert_awaited_once()
    async with AsyncSession(earning_database) as session:
        rows = (await session.scalars(select(ChannelClaim))).all()
        assert len(rows) == 1 and rows[0].status == "completed"


async def test_postgres_migration_defaults_and_unique_constraint(earning_database):
    task = await seed_task(earning_database)
    async with AsyncSession(earning_database) as session:
        assert await session.scalar(text("SELECT earning FROM settings WHERE id=1")) == {}
        dao = EarningDaoImpl(session)
        await dao.save_claim(ChannelClaimDto(task_id=task.id, user_id=1, payload={"days": 3}))
        await session.commit()
        with pytest.raises(IntegrityError):
            # Exercise the actual database constraint independently of DAO upserts.
            session.add(
                ChannelClaim(
                    task_id=task.id,
                    user_id=1,
                    payload={},
                    status="pending",
                    subscription_applied=False,
                    reset_started=False,
                    reset_applied=False,
                )
            )
            await session.flush()
        await session.rollback()
        stored = await dao.get_claim(task.id, 1)
        assert stored.payload == {"days": 3}

    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0052_add_channel_earning"
    )

    def downgrade_upgrade(connection):
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            migration.upgrade()
            importlib.import_module(
                "src.infrastructure.database.migrations.versions.0053_add_channel_claim_completed_at"
            ).upgrade()

    async with earning_database.begin() as connection:
        await connection.run_sync(downgrade_upgrade)
        assert await connection.scalar(text("SELECT earning FROM settings WHERE id=1")) == {}


async def test_postgres_channel_statistics_use_completion_date_and_calendar_boundaries(
    earning_database,
):
    now = datetime(2026, 10, 17, 12, tzinfo=UTC)
    day_start = now.replace(hour=0)
    week_start = day_start - timedelta(days=now.weekday())
    month_start = day_start.replace(day=1)
    samples = [
        (now, "completed", False),
        (day_start, "completed", False),
        (week_start, "completed", False),
        (month_start, "completed", False),
        (month_start - timedelta(seconds=1), "completed", False),
        (now, "completed", True),
        (now, "pending", False),
        (now + timedelta(days=1), "completed", False),
    ]
    for completed_at, status, deleted in samples:
        task = await seed_task(earning_database)
        async with AsyncSession(earning_database) as session:
            await EarningDaoImpl(session).save_task(replace(task, deleted=deleted))
            session.add(
                ChannelClaim(
                    task_id=task.id,
                    user_id=1,
                    payload={},
                    status=status,
                    subscription_applied=True,
                    reset_started=False,
                    reset_applied=False,
                    created_at=month_start - timedelta(days=30),
                    updated_at=completed_at,
                    completed_at=completed_at,
                )
            )
            await session.commit()
    async with AsyncSession(earning_database) as session:
        statistics = await EarningDaoImpl(session).get_statistics(now)
        assert (statistics.daily, statistics.weekly, statistics.monthly, statistics.total) == (
            3,
            4,
            5,
            6,
        )


async def test_postgres_completion_timestamp_is_set_once(earning_database, monkeypatch):
    task = await seed_task(earning_database)
    now = datetime(2026, 10, 17, 12, tzinfo=UTC)
    monkeypatch.setattr("src.infrastructure.database.dao.earning.datetime_now", lambda: now)
    async with AsyncSession(earning_database, expire_on_commit=False) as session:
        dao = EarningDaoImpl(session)
        pending = ChannelClaimDto(task_id=task.id, user_id=1)
        await dao.save_claim(pending)
        await session.commit()
        assert await session.scalar(select(ChannelClaim.completed_at)) is None
        pending.status = "completed"
        await dao.save_claim(pending)
        await session.commit()
        assert await session.scalar(select(ChannelClaim.completed_at)) == now
        monkeypatch.setattr(
            "src.infrastructure.database.dao.earning.datetime_now",
            lambda: now + timedelta(days=1),
        )
        await dao.save_claim(pending)
        await session.commit()
        assert await session.scalar(select(ChannelClaim.completed_at)) == now
        stored = await dao.get_task(task.id)
        assert stored.completed_claims_count == 1
        tasks = await dao.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].claims_count == tasks[0].completed_claims_count == 1


async def test_postgres_completion_migration_preserves_existing_history(earning_database):
    task = await seed_task(earning_database)
    now = datetime(2026, 10, 17, 12, tzinfo=UTC)
    async with AsyncSession(earning_database) as session:
        for user_id, status in ((1, "completed"), (2, "pending")):
            await EarningDaoImpl(session).save_claim(
                ChannelClaimDto(
                    task_id=task.id,
                    user_id=user_id,
                    status=status,
                )
            )
        await session.commit()
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0053_add_channel_claim_completed_at"
    )

    def downgrade(connection):
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()

    def upgrade(connection):
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

    async with earning_database.begin() as connection:
        await connection.run_sync(downgrade)
        await connection.execute(text("UPDATE channel_claims SET updated_at=:time"), {"time": now})
        await connection.run_sync(upgrade)
        rows = (
            await connection.execute(
                text("SELECT user_id, completed_at FROM channel_claims ORDER BY user_id")
            )
        ).all()
        assert rows == [(1, now), (2, None)]
