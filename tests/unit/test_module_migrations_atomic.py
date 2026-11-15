"""A module migration is applied all at once or not at all.

The runner wraps each migration file and its applied_migrations record in one SQLite
transaction. If a start is interrupted part-way (a statement fails, the process is killed,
the power goes), the database is left exactly as before that migration, and the next start
simply runs it again. Before this, an ALTER TABLE that had already gone through was not
recorded, so every later start failed with "duplicate column" and the app never came up.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from pathlib import Path

import pytest

from backend.core.database import Database

MODULES = Path(__file__).resolve().parents[2] / "backend" / "modules"
FANPILOT_MIGRATIONS = MODULES / "fanpilot" / "migrations"


async def _columns(db: Database, table: str) -> set[str]:
    return {r["name"] for r in await db.fetchall(f"PRAGMA table_info({table})")}


async def _applied(db: Database, module: str) -> list[str]:
    rows = await db.fetchall(
        "SELECT version FROM applied_migrations WHERE module = ? ORDER BY version", (module,)
    )
    return [r["version"] for r in rows]


async def test_a_failing_migration_leaves_nothing_behind_and_can_be_retried(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_base.sql").write_text("CREATE TABLE t (a INTEGER);\n", encoding="utf-8")
    second = migrations / "002_add.sql"
    second.write_text(
        "ALTER TABLE t ADD COLUMN b TEXT;\n"
        "ALTER TABLE no_such_table ADD COLUMN c TEXT;\n",
        encoding="utf-8",
    )

    db = Database(str(tmp_path / "app.db"))
    await db.connect()
    try:
        with pytest.raises(sqlite3.OperationalError):
            await db.run_module_migrations("demo", migrations)

        # The first statement of the failed file was rolled back with it, and the file
        # was not recorded; the migration before it stays applied.
        assert await _columns(db, "t") == {"a"}
        assert await _applied(db, "demo") == ["001_base"]
        # The connection is still usable after the rollback.
        assert await db.fetchone("SELECT 1 AS ok") == {"ok": 1}

        # Next start, with the file fixed: it runs from scratch and is recorded once.
        second.write_text("ALTER TABLE t ADD COLUMN b TEXT;\n", encoding="utf-8")
        await db.run_module_migrations("demo", migrations)
        assert await _columns(db, "t") == {"a", "b"}
        assert await _applied(db, "demo") == ["001_base", "002_add"]

        # And a further start changes nothing.
        await db.run_module_migrations("demo", migrations)
        assert await _applied(db, "demo") == ["001_base", "002_add"]
    finally:
        await db.close()


async def test_an_interrupted_multi_sensor_migration_is_redone_cleanly(tmp_path):
    # The real fanpilot 002, interrupted after its first ALTER (simulated by a failing
    # statement appended to a copy), must leave no column behind, so the real file
    # applies on the next start instead of failing with "duplicate column".
    broken = tmp_path / "broken"
    broken.mkdir()
    shutil.copy(FANPILOT_MIGRATIONS / "001_initial.sql", broken / "001_initial.sql")
    real_002 = (FANPILOT_MIGRATIONS / "002_multi_sensor.sql").read_text(encoding="utf-8")
    first_alter = real_002.split(";")[0] + ";\n"
    (broken / "002_multi_sensor.sql").write_text(
        first_alter + "SELECT * FROM no_such_table;\n", encoding="utf-8"
    )

    db = Database(str(tmp_path / "fp.db"))
    await db.connect()
    try:
        with pytest.raises(sqlite3.OperationalError):
            await db.run_module_migrations("fanpilot", broken)
        assert "source_sensors" not in await _columns(db, "fan_profiles")
        assert await _applied(db, "fanpilot") == ["001_initial"]

        await db.run_module_migrations("fanpilot", FANPILOT_MIGRATIONS)
        assert {"source_sensors", "sensor_mode"} <= await _columns(db, "fan_profiles")
        assert await _applied(db, "fanpilot") == ["001_initial", "002_multi_sensor"]
    finally:
        await db.close()


_TRANSACTION_STATEMENT = re.compile(
    r"^\s*(BEGIN|COMMIT|ROLLBACK|END|SAVEPOINT|RELEASE)\b", re.IGNORECASE | re.MULTILINE
)


@pytest.mark.parametrize(
    "migration",
    sorted(MODULES.glob("*/migrations/*.sql")),
    ids=lambda p: f"{p.parent.parent.name}/{p.name}",
)
def test_migration_files_leave_transactions_to_the_runner(migration):
    # The runner opens the transaction itself; a BEGIN or COMMIT inside a file would
    # either fail ("cannot start a transaction within a transaction") or split the
    # migration from its record again.
    text = migration.read_text(encoding="utf-8")
    assert not _TRANSACTION_STATEMENT.search(text), migration
