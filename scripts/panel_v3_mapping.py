"""Extract UUID -> numeric ID mappings without restoring or executing a panel dump."""

import argparse
import gzip
import hashlib
import json
import re
import sys
import tarfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

_USERS_COPY = re.compile(r'^COPY (?:"?public"?\.)?"?users"? \((.+)\) FROM stdin;$')
_MAX_BIGINT = (1 << 63) - 1
_TARGETS = (
    ("subscriptions", "user_remna_id", "panel_user_id", False),
    ("promocode_activations", "target_remna_id", "target_panel_user_id", False),
    ("linked_devices", "panel_user_uuid", "panel_user_id", True),
    ("auth_tokens", "panel_user_uuid", "panel_user_id", True),
)


@dataclass(frozen=True)
class PanelUserId:
    uuid: UUID
    id: int


def _validate_columns(columns: list[str]) -> None:
    id_columns = [name for name in ("t_id", "id") if name in columns]
    if "uuid" not in columns or len(id_columns) != 1 or len(set(columns)) != len(columns):
        raise ValueError("users COPY must contain uuid and exactly one of t_id/id")


def _iter_user_rows(lines: Iterable[str]) -> Iterator[tuple[list[str], str]]:
    in_copy = False
    in_users = False
    found_users = False
    columns: list[str] = []

    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if in_copy:
            if line == r"\.":
                in_copy = in_users = False
                continue
            if not in_users:
                continue
            yield columns, line
            continue

        if not (line.startswith("COPY ") and line.endswith(" FROM stdin;")):
            continue
        in_copy = True
        match = _USERS_COPY.fullmatch(line)
        if match is None:
            continue
        if found_users:
            raise ValueError("Multiple users COPY blocks are not supported")
        found_users = in_users = True
        columns = [name.strip().strip('"') for name in match.group(1).split(",")]
        _validate_columns(columns)

    if in_users:
        raise ValueError("Incomplete users COPY block")
    if not found_users:
        raise ValueError("No users COPY block found in the dump")


def _parse_user_row(columns: list[str], line: str, row_number: int) -> PanelUserId:
    values = line.split("\t")
    if len(values) != len(columns):
        raise ValueError(f"users row {row_number}: unexpected number of columns")
    try:
        user_uuid = UUID(values[columns.index("uuid")])
    except ValueError:
        raise ValueError(f"users row {row_number}: invalid UUID") from None
    id_column = "t_id" if "t_id" in columns else "id"
    raw_id = values[columns.index(id_column)]
    if not re.fullmatch(r"[0-9]+", raw_id):
        raise ValueError(f"users row {row_number}: invalid numeric ID")
    user_id = int(raw_id)
    if not 1 <= user_id <= _MAX_BIGINT:
        raise ValueError(f"users row {row_number}: ID outside positive bigint range")
    return PanelUserId(user_uuid, user_id)


def parse_users_copy(lines: Iterable[str]) -> list[PanelUserId]:
    """Read only the users COPY block, ignoring every other table and SQL statement."""
    users: list[PanelUserId] = []
    uuids: set[UUID] = set()
    ids: set[int] = set()
    for row_number, (columns, line) in enumerate(_iter_user_rows(lines), start=1):
        user = _parse_user_row(columns, line, row_number)
        if user.uuid in uuids or user.id in ids:
            raise ValueError(f"users row {row_number}: duplicate UUID or numeric ID")
        uuids.add(user.uuid)
        ids.add(user.id)
        users.append(user)
    if not users:
        raise ValueError("No user mappings found in the dump")
    return sorted(users, key=lambda user: user.id)


def read_backup(path: Path) -> list[PanelUserId]:
    if path.name.endswith(".sql.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as dump:
            return parse_users_copy(dump)
    if path.suffix == ".sql":
        with path.open(encoding="utf-8") as dump:
            return parse_users_copy(dump)
    with tarfile.open(path, "r:gz") as archive:
        members = [
            member
            for member in archive.getmembers()
            if member.isfile() and member.name.endswith(".sql.gz")
        ]
        if len(members) != 1:
            raise ValueError("Panel archive must contain exactly one .sql.gz dump")
        source = archive.extractfile(members[0])
        if source is None:
            raise ValueError("Cannot read the SQL dump from the archive")
        with source, gzip.open(source, "rt", encoding="utf-8") as dump:
            return parse_users_copy(dump)


def build_backfill_sql(users: list[PanelUserId], *, commit: bool = False) -> str:
    """Generate fixed SQL using only validated UUIDs/integers, never SQL from the dump."""
    if not users:
        raise ValueError("Cannot generate a backfill with no mappings")
    # Validate programmatic callers as well as the COPY parser.
    if any(
        not isinstance(user.uuid, UUID)
        or type(user.id) is not int
        or not 1 <= user.id <= _MAX_BIGINT
        for user in users
    ):
        raise ValueError("Invalid UUID/numeric ID mapping")
    if len({user.uuid for user in users}) != len(users) or len({u.id for u in users}) != len(users):
        raise ValueError("Duplicate UUID or numeric ID mapping")

    sql = [
        "-- Run ONLY against the Remnashop database after Alembic revision 0049.",
        "-- Existing UUIDs are preserved. Preview rolls back every UPDATE.",
        "-- Stop the app, worker and scheduler when applying the final mapping.",
        "BEGIN;",
        "CREATE TEMP TABLE panel_v3_user_map (",
        "    uuid uuid PRIMARY KEY, id bigint NOT NULL UNIQUE CHECK (id > 0)",
        ") ON COMMIT DROP;",
    ]
    for offset in range(0, len(users), 500):
        values = ",\n".join(
            f"    ('{user.uuid}', {user.id})" for user in users[offset : offset + 500]
        )
        sql.append(f"INSERT INTO panel_v3_user_map (uuid, id) VALUES\n{values};")
    sql.append(
        "LOCK TABLE subscriptions, promocode_activations, linked_devices, auth_tokens "
        "IN SHARE ROW EXCLUSIVE MODE;"
    )
    for table, legacy_column, numeric_column, text_uuid in _TARGETS:
        legacy = f"lower(t.{legacy_column})" if text_uuid else f"t.{legacy_column}"
        mapping = "m.uuid::text" if text_uuid else "m.uuid"
        match = f"{legacy} = {mapping}"
        sql.extend(
            [
                f"-- {table}: refuse to overwrite a different ID that is already saved.",
                "DO $$ BEGIN",
                "    IF EXISTS (",
                f"        SELECT 1 FROM {table} t JOIN panel_v3_user_map m ON {match}",
                f"        WHERE t.{numeric_column} IS NOT NULL AND t.{numeric_column} <> m.id",
                "    ) THEN",
                f"        RAISE EXCEPTION 'Conflicting numeric panel IDs in {table}';",
                "    END IF;",
                "END $$;",
                f"UPDATE {table} t SET {numeric_column} = m.id",
                f"FROM panel_v3_user_map m WHERE {match} AND t.{numeric_column} IS NULL;",
                f"SELECT '{table}' AS table_name,",
                "    count(*) FILTER (WHERE m.id IS NOT NULL) AS matched_rows,",
                f"    count(*) FILTER (WHERE t.{legacy_column} IS NOT NULL AND m.id IS NULL)",
                "        AS missing_from_backup,",
                f"    count(*) FILTER (WHERE t.{numeric_column} IS NULL) AS without_numeric_id",
                f"FROM {table} t LEFT JOIN panel_v3_user_map m ON {match};",
            ]
        )
    sql.extend(
        [
            "-- Current subscriptions must be reconciled before switching to panel v3.",
            "SELECT count(*) AS current_subscriptions_without_numeric_id",
            "FROM users u JOIN subscriptions s ON s.id = u.current_subscription_id",
            "WHERE s.panel_user_id IS NULL;",
            "COMMIT;" if commit else "ROLLBACK;",
        ]
    )
    return "\n".join(sql) + "\n"


def export_mapping(backup: Path, output_dir: Path) -> int:
    users = read_backup(backup)
    with backup.open("rb") as source:
        source_sha256 = hashlib.file_digest(source, "sha256").hexdigest()
    artifacts = {
        "user-id-map.json": json.dumps(
            {
                "schema_version": 1,
                "source_sha256": source_sha256,
                "user_count": len(users),
                "users": [{"uuid": str(user.uuid), "id": user.id} for user in users],
            },
            indent=2,
        )
        + "\n",
        "backfill.preview.sql": build_backfill_sql(users),
        "backfill.apply.sql": build_backfill_sql(users, commit=True),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    if any((output_dir / name).exists() for name in artifacts):
        raise ValueError("Output files already exist; choose a new output directory")
    for name, content in artifacts.items():
        with (output_dir / name).open("x", encoding="utf-8", newline="\n") as artifact:
            artifact.write(content)
    return len(users)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path, help="Panel .tar.gz, .sql.gz or plain .sql backup")
    parser.add_argument("--output-dir", type=Path, default=Path("backups/panel-v3"))
    args = parser.parse_args()
    try:
        count = export_mapping(args.backup, args.output_dir)
    except (OSError, ValueError, EOFError, tarfile.TarError) as error:
        print(f"Mapping export failed: {error}", file=sys.stderr)  # noqa: T201
        return 1
    print(f"Exported {count} unique UUID/ID mappings to {args.output_dir}")  # noqa: T201
    print(  # noqa: T201
        "Created JSON, preview SQL (ROLLBACK), and apply SQL (COMMIT). No database was accessed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
