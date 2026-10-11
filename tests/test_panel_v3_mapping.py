import gzip
import importlib
import io
import json
import tarfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from adaptix import Retort
from alembic.migration import MigrationContext
from alembic.operations import Operations
from remnapy.enums import TrafficLimitStrategy
from sqlalchemy import create_engine, insert, select, update

from scripts.panel_v3_mapping import (
    PanelUserId,
    build_backfill_sql,
    export_mapping,
    parse_users_copy,
    read_backup,
)
from src.application.dto.subscription import RemnaSubscriptionDto
from src.core.enums import SubscriptionStatus
from src.infrastructure.database.dao.device import _preserve_panel_user_id
from src.infrastructure.database.models import (
    AuthToken,
    LinkedDevice,
    PromocodeActivation,
    Subscription,
)
from src.infrastructure.services.remnawave import RemnawaveImpl

_UUID = "617dd034-2cf1-41b6-bf15-85e7bfc5e60b"
_OTHER_UUID = "0c78b947-8f77-40ee-994a-49eb69a86b88"


def _dump(row: str = f"{_UUID}\tshort-id\t42", *, columns: str = "uuid, short_uuid, t_id") -> str:
    return f"COPY public.users ({columns}) FROM stdin;\n{row}\n\\.\n"


def test_reads_numeric_ids_by_column_name_and_ignores_other_data() -> None:
    dump = (
        "DROP TABLE users; -- Must never be executed.\n"
        "COPY public.settings (value) FROM stdin;\n"
        "COPY public.users (uuid, id) FROM stdin;\n\\.\n"
        + _dump(f"9223372036854775807\tprivate@example.org\t{_UUID}", columns="t_id, email, uuid")
    )

    assert parse_users_copy(dump.splitlines()) == [PanelUserId(UUID(_UUID), (1 << 63) - 1)]


def test_supports_renamed_id_and_quoted_column_names() -> None:
    dump = _dump(f"{_UUID}\t42", columns='"uuid", "id"')
    assert parse_users_copy(dump.splitlines()) == [PanelUserId(UUID(_UUID), 42)]


@pytest.mark.parametrize("raw_id", ["0", "-1", "9223372036854775808", r"\N", "1; DROP TABLE users"])
def test_rejects_invalid_numeric_ids_without_echoing_user_data(raw_id: str) -> None:
    with pytest.raises(ValueError, match="users row 1:") as error:
        parse_users_copy(_dump(f"{_UUID}\tsecret\t{raw_id}").splitlines())
    assert "secret" not in str(error.value)
    assert _UUID not in str(error.value)


@pytest.mark.parametrize("second_row", [f"{_UUID}\tother\t43", f"{_OTHER_UUID}\tother\t42"])
def test_rejects_duplicate_ids_and_uuids(second_row: str) -> None:
    with pytest.raises(ValueError, match="duplicate"):
        parse_users_copy(_dump(f"{_UUID}\tfirst\t42\n{second_row}").splitlines())


@pytest.mark.parametrize(
    "dump",
    [
        _dump("invalid-uuid\tsecret\t42"),
        _dump(f"{_UUID}\t42"),
        _dump(f"{_UUID}\t42\t43", columns="uuid, id, t_id"),
        _dump(f"{_UUID}\t42", columns="uuid, telegram_id"),
        _dump().replace("\\.\n", ""),
        _dump() + _dump(f"{_OTHER_UUID}\tother\t43"),
        "COPY public.users (uuid, t_id) FROM stdin;\n\\.\n",
    ],
)
def test_rejects_incomplete_or_ambiguous_dump(dump: str) -> None:
    with pytest.raises(ValueError):
        parse_users_copy(dump.splitlines())


def test_exports_nested_backup_without_exposing_secrets(tmp_path: Path) -> None:
    backup = tmp_path / "panel.tar.gz"
    with tarfile.open(backup, "w:gz") as archive:
        for name, data in [
            ("dump.sql.gz", gzip.compress(_dump().encode())),
            ("../.env", b"JWT_AUTH_SECRET=private-key"),
        ]:
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    output = tmp_path / "export"

    assert read_backup(backup) == [PanelUserId(UUID(_UUID), 42)]
    assert export_mapping(backup, output) == 1
    mapping = json.loads((output / "user-id-map.json").read_text())
    assert mapping["users"] == [{"uuid": _UUID, "id": 42}]
    assert len(mapping["source_sha256"]) == 64
    assert not (tmp_path / ".env").exists()
    for artifact in output.iterdir():
        assert "private-key" not in artifact.read_text()
        assert "short-id" not in artifact.read_text()
    with pytest.raises(ValueError, match="already exist"):
        export_mapping(backup, output)


def test_generated_sql_is_transactional_and_preserves_legacy_ids() -> None:
    users = [PanelUserId(UUID(_UUID), 42)]
    preview = build_backfill_sql(users)
    apply = build_backfill_sql(users, commit=True)

    assert preview.endswith("ROLLBACK;\n")
    assert apply == preview.removesuffix("ROLLBACK;\n") + "COMMIT;\n"
    assert "current_subscriptions_without_numeric_id" in preview
    for table, numeric_column in [
        ("subscriptions", "panel_user_id"),
        ("promocode_activations", "target_panel_user_id"),
        ("linked_devices", "panel_user_id"),
        ("auth_tokens", "panel_user_id"),
    ]:
        assert f"UPDATE {table} t SET {numeric_column} = m.id" in preview
        assert f"t.{numeric_column} IS NULL" in preview
        assert f"Conflicting numeric panel IDs in {table}" in preview
    assert "missing_from_backup" in preview
    assert "DROP COLUMN" not in preview
    assert "SET user_remna_id" not in preview


def test_migration_adds_nullable_bigints_and_can_be_reversed_offline() -> None:
    migration = importlib.import_module(
        "src.infrastructure.database.migrations.versions.0048_add_panel_user_ids"
    )
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        migration.upgrade()
        migration.downgrade()
    sql = output.getvalue()
    for model, name in [
        (Subscription, "panel_user_id"),
        (PromocodeActivation, "target_panel_user_id"),
        (LinkedDevice, "panel_user_id"),
        (AuthToken, "panel_user_id"),
    ]:
        table = model.__tablename__
        assert f"ALTER TABLE {table} ADD COLUMN {name} BIGINT;" in sql
        assert f"ALTER TABLE {table} DROP COLUMN {name};" in sql
        assert model.__table__.c[name].nullable
        assert str(model.__table__.c[name].type) == "BIGINT"


def test_numeric_id_is_collected_from_panel_and_preserved_during_sync() -> None:
    source = RemnaSubscriptionDto.from_remna_user(
        SimpleNamespace(
            uuid=UUID(_UUID),
            id=42,
            status="ACTIVE",
            expire_at=datetime(2030, 1, 1, tzinfo=UTC),
            subscription_url="https://example.org/s/test",
            traffic_limit_bytes=0,
            hwid_device_limit=1,
            traffic_limit_strategy=TrafficLimitStrategy.NO_RESET,
            tag=None,
            active_internal_squads=[],
            external_squad_uuid=None,
        )
    )
    assert source.panel_user_id == 42
    retort = Retort()
    legacy_payload = retort.dump(source)
    legacy_payload.pop("panel_user_id")
    assert retort.load(legacy_payload, RemnaSubscriptionDto).panel_user_id is None
    target = replace(source, panel_user_id=None, status=SubscriptionStatus.DISABLED)
    service = RemnawaveImpl.__new__(RemnawaveImpl)

    service.apply_sync(target, source)
    assert target.panel_user_id == 42
    assert target.status == SubscriptionStatus.ACTIVE
    service.apply_sync(target, replace(source, panel_user_id=None))
    assert target.panel_user_id == 42


@pytest.mark.parametrize("model", [LinkedDevice, AuthToken])
@pytest.mark.parametrize("new_uuid, expected_id", [(_UUID, 42), (_OTHER_UUID, None), (None, None)])
def test_rebinding_clears_numeric_id_but_same_user_preserves_it(
    model: type[LinkedDevice] | type[AuthToken], new_uuid: str | None, expected_id: int | None
) -> None:
    engine = create_engine("sqlite://")
    try:
        model.__table__.create(engine)
        data = {
            "device_id": "device-1",
            "panel_user_uuid": _UUID,
            "panel_user_id": 42,
            "created_at": datetime(2030, 1, 1, tzinfo=UTC),
            "updated_at": datetime(2030, 1, 1, tzinfo=UTC),
        }
        if model is AuthToken:
            data["token"] = "test-token"
        with engine.begin() as connection:
            connection.execute(insert(model).values(**data))
            connection.execute(
                update(model).values(
                    panel_user_uuid=new_uuid,
                    panel_user_id=_preserve_panel_user_id(model, new_uuid),
                    updated_at=datetime(2030, 1, 2, tzinfo=UTC),
                )
            )
            assert connection.scalar(select(model.panel_user_id)) == expected_id
    finally:
        engine.dispose()
