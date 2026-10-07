import asyncio
import importlib
from contextlib import asynccontextmanager
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Column, DateTime, Integer, MetaData, Table, create_engine, select
from sqlalchemy.dialects import postgresql

from src.application.dto import BroadcastDto, BroadcastMessageDto, MessagePayloadDto, UserDto
from src.application.use_cases.broadcast.commands.lifecycle import (
    FinishBroadcast,
    StartBroadcast,
    StartBroadcastDto,
)
from src.application.use_cases.broadcast.queries.audience import (
    GetBroadcastAudienceCount,
    GetBroadcastAudienceCountDto,
    GetBroadcastAudienceUsers,
    GetBroadcastAudienceUsersDto,
)
from src.core.enums import BroadcastAudience, BroadcastMessageStatus, BroadcastStatus
from src.core.exceptions import (
    BroadcastAudienceUnavailableError,
    BroadcastRepeatSourceNotFoundError,
)
from src.core.utils.time import datetime_now
from src.infrastructure.database.dao.broadcast import BroadcastDaoImpl
from src.infrastructure.database.models import Broadcast, BroadcastDelivery
from src.infrastructure.taskiq.tasks.broadcast import delete_broadcast_task, send_broadcast_task


class _History:
    def __init__(self):
        self.broadcasts = {}
        self.delivered = {}
        self.locks = {}
        self.transaction_locks = []

    async def create(self, broadcast):
        self.broadcasts[broadcast.task_id] = broadcast
        return broadcast

    async def get_by_task_id(self, task_id):
        return self.broadcasts.get(task_id)

    async def get_delivered_telegram_ids(self, campaign_id):
        return list(self.delivered.get(campaign_id, set()))

    async def record_delivery(self, campaign_id, telegram_id):
        self.delivered.setdefault(campaign_id, set()).add(telegram_id)

    async def update_status(self, task_id, status):
        self.broadcasts[task_id].status = status

    async def clear_finished_campaign(self, campaign_id):
        if not any(
            b.campaign_id == campaign_id and b.status != BroadcastStatus.DELETED
            for b in self.broadcasts.values()
        ):
            self.delivered.pop(campaign_id, None)

    async def lock_campaign_transaction(self, campaign_id):
        lock = self.locks.setdefault(campaign_id, asyncio.Lock())
        await lock.acquire()
        self.transaction_locks.append(lock)

    @asynccontextmanager
    async def lock_campaign(self, campaign_id):
        async with self.locks.setdefault(campaign_id, asyncio.Lock()):
            yield


class _Uow:
    def __init__(self, history=None):
        self.history = history

    async def commit(self):
        if self.history is not None:
            for lock in self.history.transaction_locks:
                lock.release()
            self.history.transaction_locks.clear()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        if args[0] is not None:
            await self.commit()
        return None


def _flow(monkeypatch):  # noqa: C901
    history = _History()
    users = [UserDto(id=i, telegram_id=i, name=str(i)) for i in (101, 102, 103)]
    failed = {103}
    sent = []

    async def recipients(excluded, days=None):
        return [u for u in users if u.telegram_id not in excluded]

    async def count(excluded, days=None):
        return len(await recipients(excluded, days))

    user_dao = SimpleNamespace(get_active_non_blocked=recipients, count_active_non_blocked=count)
    count_audience = GetBroadcastAudienceCount(user_dao, SimpleNamespace(), history)
    get_users = GetBroadcastAudienceUsers(user_dao, history)
    dispatcher = SimpleNamespace(start=AsyncMock())
    start = StartBroadcast(_Uow(history), history, count_audience, dispatcher)

    async def initialize(data):
        broadcast = history.broadcasts[data.task_id]
        if broadcast.messages:
            return broadcast.messages
        broadcast.messages = data.messages
        for i, message in enumerate(broadcast.messages, start=1):
            message.id = i
        broadcast.total_count = len(broadcast.messages)
        return broadcast.messages

    async def update(data):
        broadcast = history.broadcasts[data.task_id]
        for result in data.messages:
            message = next(m for m in broadcast.messages if m.id == result.id)
            message.status = result.status
            message.message_id = result.message_id
            if result.status == BroadcastMessageStatus.SENT:
                broadcast.success_count += 1
            else:
                broadcast.failed_count += 1

    async def finish(data):
        history.broadcasts[data.task_id].status = data.status

    async def notify(user, **kwargs):
        await asyncio.sleep(0)
        if user.telegram_id in failed:
            return None
        sent.append(user.telegram_id)
        return SimpleNamespace(message_id=user.telegram_id)

    monkeypatch.setattr("src.infrastructure.taskiq.tasks.broadcast.BATCH_DELAY", 0)
    worker = send_broadcast_task.original_func.__dishka_orig_func__

    async def send(broadcast, update_messages=None):
        await worker(
            broadcast,
            None,
            [],
            None,
            history,
            get_users,
            SimpleNamespace(system=initialize),
            SimpleNamespace(system=update_messages or update),
            SimpleNamespace(system=finish),
            SimpleNamespace(notify_user=notify),
        )

    return SimpleNamespace(
        history=history,
        users=users,
        failed=failed,
        sent=sent,
        start=start,
        send=send,
        dispatcher=dispatcher,
        count=count_audience,
        get_users=get_users,
    )


async def test_repeat_chain_and_cleanup_never_reset_delivery_history(monkeypatch):
    flow = _flow(monkeypatch)
    payload = MessagePayloadDto(i18n_key="msg-broadcast", i18n_kwargs={"content": "Hello"})

    async def launch(source=None):
        task_id = await flow.start.system(
            StartBroadcastDto(BroadcastAudience.ALL, payload, source_task_id=source)
        )
        broadcast = flow.history.broadcasts[task_id]
        await flow.send(broadcast)
        return broadcast

    original = await launch()
    assert original.campaign_id == original.task_id
    assert set(flow.sent) == {101, 102}

    flow.failed.clear()
    flow.users.append(UserDto(id=104, telegram_id=104, name="new"))
    first = await launch(original.task_id)
    assert first.campaign_id == original.campaign_id
    assert first.total_count == 2
    assert flow.sent.count(101) == flow.sent.count(102) == 1

    flow.users.append(UserDto(id=105, telegram_id=105, name="newer"))
    second = await launch(first.task_id)
    assert second.campaign_id == original.campaign_id
    assert second.total_count == 1
    with pytest.raises(BroadcastAudienceUnavailableError):
        await launch(original.task_id)

    del flow.history.broadcasts[original.task_id]
    del flow.history.broadcasts[first.task_id]
    flow.users.append(UserDto(id=106, telegram_id=106, name="latest"))
    third = await launch(second.task_id)
    assert third.campaign_id == original.campaign_id
    assert third.total_count == 1
    assert flow.sent == [101, 102, 103, 104, 105, 106]


async def test_simultaneous_repeats_recheck_recipients_after_waiting_for_lock(monkeypatch):
    flow = _flow(monkeypatch)
    flow.failed.clear()
    campaign_id = uuid4()
    repeats = [
        BroadcastDto(
            task_id=uuid4(),
            campaign_id=campaign_id,
            status=BroadcastStatus.PROCESSING,
            audience=BroadcastAudience.ALL,
            payload=MessagePayloadDto(i18n_key="msg-broadcast"),
        )
        for _ in range(2)
    ]
    for broadcast in repeats:
        await flow.history.create(broadcast)

    await asyncio.gather(*(flow.send(b) for b in repeats))

    assert sorted(flow.sent) == [101, 102, 103]
    assert all(b.status == BroadcastStatus.COMPLETED for b in repeats)
    assert sorted(b.total_count for b in repeats) == [0, 3]


async def test_duplicate_worker_delivery_and_canceled_task_do_not_resend(monkeypatch):
    flow = _flow(monkeypatch)
    flow.failed.clear()
    broadcast = BroadcastDto(
        task_id=uuid4(),
        campaign_id=uuid4(),
        status=BroadcastStatus.PROCESSING,
        audience=BroadcastAudience.ALL,
        payload=MessagePayloadDto(i18n_key="msg-broadcast"),
    )
    await flow.history.create(broadcast)
    await flow.send(broadcast)
    await flow.send(broadcast)
    assert sorted(flow.sent) == [101, 102, 103]
    broadcast.status = BroadcastStatus.CANCELED
    await flow.send(broadcast)
    assert len(flow.sent) == 3


async def test_manual_exclusions_are_combined_with_all_successful_receipts(monkeypatch):
    flow = _flow(monkeypatch)
    campaign_id = uuid4()
    await flow.history.record_delivery(campaign_id, 101)
    excluded = [102]
    count = await flow.count.system(
        GetBroadcastAudienceCountDto(
            BroadcastAudience.ALL, excluded_telegram_ids=excluded, campaign_id=campaign_id
        )
    )
    users = await flow.get_users.system(
        GetBroadcastAudienceUsersDto(
            BroadcastAudience.ALL, excluded_telegram_ids=excluded, campaign_id=campaign_id
        )
    )
    assert count == 1
    assert [u.telegram_id for u in users] == [103]
    assert excluded == [102]


async def test_missing_repeat_source_does_not_create_independent_broadcast(monkeypatch):
    flow = _flow(monkeypatch)
    with pytest.raises(BroadcastRepeatSourceNotFoundError):
        await flow.start.system(
            StartBroadcastDto(
                BroadcastAudience.ALL, MessagePayloadDto(i18n_key="test"), source_task_id=uuid4()
            )
        )
    assert not flow.history.broadcasts
    flow.dispatcher.start.assert_not_awaited()


@pytest.mark.parametrize(
    "status",
    [BroadcastMessageStatus.SENT, BroadcastMessageStatus.EDITED, BroadcastMessageStatus.DELETED],
)
async def test_persisted_delivery_history_is_idempotent_and_survives_message_deletion(status):
    campaign_id = uuid4()
    rows = SimpleNamespace(all=lambda: [(campaign_id, 101)])
    session = AsyncMock()
    session.execute.side_effect = [None, rows, None]
    dao = BroadcastDaoImpl.__new__(BroadcastDaoImpl)
    dao.session = session

    await dao.bulk_update_messages(
        [BroadcastMessageDto(id=1, user_id=1, user_telegram_id=101, message_id=12, status=status)]
    )

    receipt_insert = session.execute.call_args_list[-1].args[0]
    sql = str(receipt_insert.compile(dialect=postgresql.dialect()))
    assert "INSERT INTO broadcast_deliveries" in sql
    assert "ON CONFLICT DO NOTHING" in sql
    params = receipt_insert.compile(dialect=postgresql.dialect()).params
    assert campaign_id in params.values()
    assert 101 in params.values()
    assert not BroadcastDelivery.__table__.foreign_keys


async def test_failed_send_does_not_mark_recipient_as_delivered():
    dao = BroadcastDaoImpl.__new__(BroadcastDaoImpl)
    dao.session = AsyncMock()
    await dao.bulk_update_messages(
        [
            BroadcastMessageDto(
                id=1, user_id=1, user_telegram_id=101, status=BroadcastMessageStatus.FAILED
            )
        ]
    )
    dao.session.execute.assert_awaited_once()


def test_migration_preserves_legacy_successes_and_removed_messages():
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0046_add_broadcast_delivery_history"
    )
    with Operations.context(context):
        migration.upgrade()
    sql = output.getvalue()
    assert "UPDATE broadcasts SET campaign_id = task_id" in sql
    assert "PRIMARY KEY (campaign_id, telegram_id)" in sql
    assert "m.status IN ('SENT', 'EDITED', 'DELETED')" in sql
    assert "COALESCE(m.user_telegram_id, u.telegram_id)" in sql
    assert "FOREIGN KEY" not in sql


async def test_cleanup_locks_campaign_before_deleting_old_runs_and_clearing_receipts():
    campaign_id = uuid4()
    result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [1]))
    dao = BroadcastDaoImpl.__new__(BroadcastDaoImpl)
    dao.session = SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [campaign_id])),
        scalar=AsyncMock(return_value=True),
        execute=AsyncMock(return_value=result),
    )
    assert await dao.delete_old() == 1
    dao.session.scalar.assert_awaited_once()
    stmt = dao.session.execute.call_args_list[0].args[0]
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "DELETE FROM broadcasts" in sql
    assert "broadcasts.status != 'PROCESSING'" in sql
    assert "broadcasts.campaign_id =" in sql
    cleanup_stmt = dao.session.execute.call_args_list[1].args[0]
    cleanup_sql = str(
        cleanup_stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "DELETE FROM broadcast_deliveries" in cleanup_sql
    assert "NOT (EXISTS" in cleanup_sql
    assert "broadcasts.status != 'DELETED'" in cleanup_sql


async def test_delivery_receipts_survive_a_batch_stats_failure(monkeypatch):
    flow = _flow(monkeypatch)
    flow.failed.clear()
    original = BroadcastDto(
        task_id=uuid4(),
        campaign_id=uuid4(),
        status=BroadcastStatus.PROCESSING,
        audience=BroadcastAudience.ALL,
        payload=MessagePayloadDto(i18n_key="test"),
    )
    await flow.history.create(original)
    await flow.send(original, update_messages=AsyncMock(side_effect=RuntimeError("commit failed")))

    assert original.status == BroadcastStatus.ERROR
    assert set(await flow.history.get_delivered_telegram_ids(original.campaign_id)) == {
        101,
        102,
        103,
    }
    with pytest.raises(BroadcastAudienceUnavailableError):
        await flow.start.system(
            StartBroadcastDto(
                BroadcastAudience.ALL, original.payload, source_task_id=original.task_id
            )
        )
    assert len(flow.sent) == 3


def _engine_stub(monkeypatch, dao):
    events = []
    connection = SimpleNamespace(execute=AsyncMock(), scalar=AsyncMock(side_effect=[False, True]))

    @asynccontextmanager
    async def transaction():
        events.append("transaction")
        try:
            yield connection
        finally:
            events.append("release_transaction")

    connection.begin = transaction

    class Engine:
        begin = staticmethod(transaction)

        @asynccontextmanager
        async def connect(self):
            events.append("connect")
            try:
                yield connection
            finally:
                events.append("release_connection")

    monkeypatch.setattr("src.infrastructure.database.dao.broadcast.AsyncEngine", Engine)
    dao.session = SimpleNamespace(bind=Engine())
    return connection, events


async def test_database_campaign_lock_waits_and_releases_on_cancellation(monkeypatch):
    dao = BroadcastDaoImpl.__new__(BroadcastDaoImpl)
    connection, events = _engine_stub(monkeypatch, dao)
    sleep = AsyncMock()
    monkeypatch.setattr("src.infrastructure.database.dao.broadcast.asyncio.sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        async with dao.lock_campaign(uuid4()):
            assert connection.scalar.await_count == 2
            raise asyncio.CancelledError

    sleep.assert_awaited_once_with(1)
    assert events == ["connect", "transaction", "release_transaction", "release_connection"]
    assert "idle_in_transaction_session_timeout = 0" in str(connection.execute.call_args.args[0])
    assert "pg_try_advisory_xact_lock" in str(connection.scalar.call_args.args[0])


async def test_success_receipt_commits_on_a_separate_database_connection(monkeypatch):
    dao = BroadcastDaoImpl.__new__(BroadcastDaoImpl)
    connection, events = _engine_stub(monkeypatch, dao)
    campaign_id = uuid4()
    await dao.record_delivery(campaign_id, 123)

    assert events == ["transaction", "release_transaction"]
    stmt = connection.execute.call_args.args[0]
    compiled = stmt.compile(dialect=postgresql.dialect())
    assert "ON CONFLICT DO NOTHING" in str(compiled)
    assert compiled.params["campaign_id"] == campaign_id
    assert compiled.params["telegram_id"] == 123
    assert "delivered_at" not in compiled.params


def test_migration_creates_compact_history_only_for_available_campaigns():
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0046_add_broadcast_delivery_history"
    )
    with Operations.context(context):
        migration.upgrade()
    sql = output.getvalue()
    assert "delivered_at" not in sql
    assert "INSERT INTO broadcast_deliveries (campaign_id, telegram_id)" in sql
    assert "AND b.status != 'DELETED'" in sql
    assert list(BroadcastDelivery.__table__.columns.keys()) == ["campaign_id", "telegram_id"]

    output.seek(0)
    output.truncate()
    with Operations.context(context):
        migration.downgrade()
    assert "DROP TABLE broadcast_deliveries" in output.getvalue()
    assert "DROP COLUMN campaign_id" in output.getvalue()


def _deletion(flow, bot=None):
    async def bulk_update(messages):
        # Deleting a Telegram message still records that its recipient received it.
        for broadcast in flow.history.broadcasts.values():
            for message in messages:
                if message in broadcast.messages and message.message_id is not None:
                    await flow.history.record_delivery(
                        broadcast.campaign_id, message.user_telegram_id
                    )

    worker = delete_broadcast_task.original_func.__dishka_orig_func__
    bot = bot or SimpleNamespace(delete_message=AsyncMock(return_value=True))
    bulk = SimpleNamespace(system=AsyncMock(side_effect=bulk_update))
    finish = FinishBroadcast(_Uow(), flow.history)
    notifier = SimpleNamespace(notify_admins=AsyncMock())

    async def delete(broadcast):
        return await worker(broadcast, flow.history, bot, bulk, finish, notifier)

    return SimpleNamespace(delete=delete, bot=bot, bulk=bulk, notifier=notifier)


def _completed_broadcast(campaign_id):
    return BroadcastDto(
        id=1,
        task_id=uuid4(),
        campaign_id=campaign_id,
        status=BroadcastStatus.COMPLETED,
        audience=BroadcastAudience.ALL,
        payload=MessagePayloadDto(i18n_key="test"),
        messages=[
            BroadcastMessageDto(
                id=1,
                user_id=101,
                user_telegram_id=101,
                message_id=12,
                status=BroadcastMessageStatus.SENT,
            )
        ],
    )


@pytest.mark.parametrize(
    "remaining_status",
    [
        BroadcastStatus.COMPLETED,
        BroadcastStatus.PROCESSING,
        BroadcastStatus.CANCELED,
        BroadcastStatus.ERROR,
    ],
)
async def test_deletion_preserves_chain_history_until_last_available_run_is_deleted(
    monkeypatch, remaining_status
):
    flow = _flow(monkeypatch)
    campaign_id = uuid4()
    original = _completed_broadcast(campaign_id)
    repeat = _completed_broadcast(campaign_id)
    repeat.status = remaining_status
    unrelated = _completed_broadcast(uuid4())
    for broadcast in (original, repeat, unrelated):
        await flow.history.create(broadcast)
    await flow.history.record_delivery(campaign_id, 101)
    await flow.history.record_delivery(unrelated.campaign_id, 102)
    deletion = _deletion(flow)

    await deletion.delete(original)
    assert original.status == BroadcastStatus.DELETED
    assert await flow.history.get_delivered_telegram_ids(campaign_id) == [101]

    await deletion.delete(repeat)
    assert repeat.status == BroadcastStatus.DELETED
    assert not await flow.history.get_delivered_telegram_ids(campaign_id)
    assert await flow.history.get_delivered_telegram_ids(unrelated.campaign_id) == [102]

    with pytest.raises(BroadcastRepeatSourceNotFoundError):
        await flow.start.system(
            StartBroadcastDto(
                BroadcastAudience.ALL, original.payload, source_task_id=original.task_id
            )
        )
    assert await deletion.delete(original) == (0, 0, 0)
    assert not await flow.history.get_delivered_telegram_ids(campaign_id)
    assert deletion.bulk.system.await_count == 2


async def test_deleting_empty_last_run_clears_history(monkeypatch):
    flow = _flow(monkeypatch)
    broadcast = _completed_broadcast(uuid4())
    broadcast.messages.clear()
    await flow.history.create(broadcast)
    await flow.history.record_delivery(broadcast.campaign_id, 101)
    deletion = _deletion(flow)

    assert await deletion.delete(broadcast) == (0, 0, 0)
    assert broadcast.status == BroadcastStatus.DELETED
    assert not await flow.history.get_delivered_telegram_ids(broadcast.campaign_id)
    deletion.bot.delete_message.assert_not_awaited()


async def test_failed_deletion_keeps_history_and_source_available(monkeypatch):
    flow = _flow(monkeypatch)
    broadcast = _completed_broadcast(uuid4())
    await flow.history.create(broadcast)
    await flow.history.record_delivery(broadcast.campaign_id, 101)
    deletion = _deletion(flow)
    deletion.bulk.system.side_effect = RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        await deletion.delete(broadcast)
    assert broadcast.status == BroadcastStatus.COMPLETED
    assert await flow.history.get_delivered_telegram_ids(broadcast.campaign_id) == [101]
    deletion.notifier.notify_admins.assert_not_awaited()


async def test_repeat_waiting_for_deletion_cannot_restart_cleared_chain(monkeypatch):
    flow = _flow(monkeypatch)
    source = _completed_broadcast(uuid4())
    await flow.history.create(source)
    await flow.history.record_delivery(source.campaign_id, 101)
    deleting = asyncio.Event()
    resume_deletion = asyncio.Event()
    repeat_waiting = asyncio.Event()

    async def delete_message(**kwargs):
        deleting.set()
        await resume_deletion.wait()
        return True

    lock_transaction = flow.history.lock_campaign_transaction

    async def acquire(campaign_id):
        repeat_waiting.set()
        await lock_transaction(campaign_id)

    flow.history.lock_campaign_transaction = acquire
    deletion = _deletion(flow, SimpleNamespace(delete_message=delete_message))
    deletion_task = asyncio.create_task(deletion.delete(source))
    await asyncio.wait_for(deleting.wait(), timeout=2)
    repeat_task = asyncio.create_task(
        flow.start.system(
            StartBroadcastDto(BroadcastAudience.ALL, source.payload, source_task_id=source.task_id)
        )
    )
    await asyncio.wait_for(repeat_waiting.wait(), timeout=2)
    resume_deletion.set()
    await asyncio.wait_for(deletion_task, timeout=2)
    with pytest.raises(BroadcastRepeatSourceNotFoundError):
        await asyncio.wait_for(repeat_task, timeout=2)
    assert len(flow.history.broadcasts) == 1
    assert not await flow.history.get_delivered_telegram_ids(source.campaign_id)
    flow.dispatcher.start.assert_not_awaited()


async def test_deletion_after_repeat_creation_preserves_delivery_history(monkeypatch):
    flow = _flow(monkeypatch)
    source = _completed_broadcast(uuid4())
    await flow.history.create(source)
    await flow.history.record_delivery(source.campaign_id, 101)
    counting = asyncio.Event()
    resume_creation = asyncio.Event()
    count_audience = flow.start.get_broadcast_audience_count

    async def count(data):
        counting.set()
        await resume_creation.wait()
        return await count_audience.system(data)

    flow.start.get_broadcast_audience_count = SimpleNamespace(system=count)
    repeat_task = asyncio.create_task(
        flow.start.system(
            StartBroadcastDto(BroadcastAudience.ALL, source.payload, source_task_id=source.task_id)
        )
    )
    await asyncio.wait_for(counting.wait(), timeout=2)
    deletion_task = asyncio.create_task(_deletion(flow).delete(source))
    await asyncio.sleep(0)
    assert not deletion_task.done()
    resume_creation.set()
    repeat_id = await asyncio.wait_for(repeat_task, timeout=2)
    await asyncio.wait_for(deletion_task, timeout=2)
    assert flow.history.broadcasts[repeat_id].status == BroadcastStatus.PROCESSING
    assert await flow.history.get_delivered_telegram_ids(source.campaign_id) == [101]


async def test_transaction_campaign_lock_uses_same_key_as_worker_lock(monkeypatch):
    dao = BroadcastDaoImpl.__new__(BroadcastDaoImpl)
    dao.session = SimpleNamespace(scalar=AsyncMock(side_effect=[False, True]))
    sleep = AsyncMock()
    monkeypatch.setattr("src.infrastructure.database.dao.broadcast.asyncio.sleep", sleep)
    campaign_id = uuid4()
    await dao.lock_campaign_transaction(campaign_id)
    sleep.assert_awaited_once_with(1)
    compiled = dao.session.scalar.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "pg_try_advisory_xact_lock" in str(compiled)
    assert campaign_id.int & ((1 << 63) - 1) in compiled.params.values()


@pytest.fixture
def cleanup_database():
    # Execute the DAO's actual DELETE/NOT EXISTS statements against a small SQL
    # database. PostgreSQL advisory locking is tested separately above.
    engine = create_engine("sqlite://")
    metadata = MetaData()
    broadcasts = Table(
        "broadcasts",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("task_id", Broadcast.__table__.c.task_id.type),
        Column("campaign_id", Broadcast.__table__.c.campaign_id.type, nullable=False),
        Column("status", Broadcast.__table__.c.status.type, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True)),
    )
    deliveries = BroadcastDelivery.__table__.to_metadata(metadata)
    metadata.create_all(engine)
    with engine.begin() as connection:
        # The model's onupdate uses PostgreSQL timezone('UTC', now()).
        connection.connection.driver_connection.create_function(
            "timezone", 2, lambda zone, timestamp: timestamp
        )

        async def execute(stmt):
            return connection.execute(stmt)

        async def scalars(stmt):
            return connection.execute(stmt).scalars()

        dao = BroadcastDaoImpl.__new__(BroadcastDaoImpl)
        dao.session = SimpleNamespace(execute=execute, scalars=scalars)
        dao.lock_campaign_transaction = AsyncMock()
        yield SimpleNamespace(
            dao=dao, connection=connection, broadcasts=broadcasts, deliveries=deliveries
        )
    engine.dispose()


@pytest.mark.parametrize(
    "remaining_status",
    [None, BroadcastStatus.DELETED, BroadcastStatus.COMPLETED, BroadcastStatus.PROCESSING],
)
async def test_sql_cleanup_requires_no_remaining_repeatable_run(cleanup_database, remaining_status):
    db = cleanup_database
    campaign_id = uuid4()
    unrelated_id = uuid4()
    db.connection.execute(
        db.deliveries.insert(),
        [
            {"campaign_id": campaign_id, "telegram_id": 101},
            {"campaign_id": unrelated_id, "telegram_id": 102},
        ],
    )
    if remaining_status is not None:
        db.connection.execute(
            db.broadcasts.insert().values(
                campaign_id=campaign_id, status=remaining_status, created_at=datetime_now()
            )
        )

    await db.dao.clear_finished_campaign(campaign_id)
    remaining = set(db.connection.execute(select(db.deliveries)).all())
    assert (unrelated_id, 102) in remaining
    assert ((campaign_id, 101) in remaining) == (
        remaining_status not in (None, BroadcastStatus.DELETED)
    )


async def test_sql_expiry_keeps_chain_until_last_repeat_expires(cleanup_database):
    db = cleanup_database
    campaign_id, orphan_id, processing_id = uuid4(), uuid4(), uuid4()
    old = datetime_now() - timedelta(days=20)
    db.connection.execute(
        db.broadcasts.insert(),
        [
            {"id": 1, "campaign_id": campaign_id, "status": "COMPLETED", "created_at": old},
            {
                "id": 2,
                "campaign_id": campaign_id,
                "status": "COMPLETED",
                "created_at": datetime_now(),
            },
            {"id": 3, "campaign_id": orphan_id, "status": "COMPLETED", "created_at": old},
            {"id": 4, "campaign_id": processing_id, "status": "PROCESSING", "created_at": old},
        ],
    )
    db.connection.execute(
        db.deliveries.insert(),
        [
            {"campaign_id": key, "telegram_id": 101}
            for key in (campaign_id, orphan_id, processing_id)
        ],
    )

    assert await db.dao.delete_old() == 2
    assert set(db.connection.execute(select(db.broadcasts.c.id)).scalars()) == {2, 4}
    assert set(db.connection.execute(select(db.deliveries.c.campaign_id)).scalars()) == {
        campaign_id,
        processing_id,
    }

    db.connection.execute(
        db.broadcasts.update().where(db.broadcasts.c.id == 2).values(created_at=old)
    )
    assert await db.dao.delete_old() == 1
    assert set(db.connection.execute(select(db.deliveries.c.campaign_id)).scalars()) == {
        processing_id
    }


@pytest.mark.parametrize("status", [BroadcastStatus.DELETED, BroadcastStatus.COMPLETED])
async def test_delayed_worker_cannot_revive_deleted_run(cleanup_database, status):
    db = cleanup_database
    task_id = uuid4()
    db.connection.execute(
        db.broadcasts.insert().values(
            task_id=task_id,
            campaign_id=uuid4(),
            status=status,
            created_at=datetime_now(),
        )
    )
    await db.dao.update_status(task_id, BroadcastStatus.ERROR)
    expected = (
        BroadcastStatus.DELETED if status == BroadcastStatus.DELETED else BroadcastStatus.ERROR
    )
    assert db.connection.scalar(select(db.broadcasts.c.status)) == expected
