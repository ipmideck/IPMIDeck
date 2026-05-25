"""SQLite database manager with async support and migration runner."""

from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger("ipmilink.database")

# Core tables (not module-specific)
CORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS servers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    host TEXT NOT NULL,
    port INTEGER DEFAULT 623,
    username_enc TEXT NOT NULL,
    password_enc TEXT NOT NULL,
    vendor TEXT DEFAULT 'dell',
    color TEXT DEFAULT '#2563eb',
    poll_interval INTEGER DEFAULT 5,
    fanpilot_profile_id INTEGER,
    fanpilot_enabled INTEGER DEFAULT 0,
    is_online INTEGER DEFAULT 0,
    last_seen DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dashboard_layouts (
    user_id INTEGER DEFAULT 0,
    layout TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id)
);

CREATE TABLE IF NOT EXISTS command_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id TEXT REFERENCES servers(id) ON DELETE CASCADE,
    command_type TEXT NOT NULL,
    command_detail TEXT,
    result TEXT,
    error_message TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS applied_migrations (
    module TEXT NOT NULL,
    version TEXT NOT NULL,
    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (module, version)
);
"""


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.executescript(CORE_SCHEMA)
        await self._db.commit()
        logger.info("Database connected: %s", self.db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.commit()
            await self._db.close()
            self._db = None
            logger.info("Database closed")

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database not connected")
        return self._db

    async def execute(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        return await self.conn.execute(sql, params)

    async def executemany(self, sql: str, params_list: list[tuple]) -> aiosqlite.Cursor:
        return await self.conn.executemany(sql, params_list)

    async def fetchone(self, sql: str, params: tuple = ()) -> dict | None:
        cursor = await self.conn.execute(sql, params)
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        cursor = await self.conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def commit(self) -> None:
        await self.conn.commit()

    async def rollback(self) -> None:
        await self.conn.rollback()

    async def get_config(self, key: str, default: str | None = None) -> str | None:
        row = await self.fetchone("SELECT value FROM app_config WHERE key = ?", (key,))
        return row["value"] if row else default

    async def set_config(self, key: str, value: str) -> None:
        await self.execute(
            "INSERT INTO app_config (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
            (key, value),
        )
        await self.commit()

    async def run_module_migrations(self, module_id: str, migrations_dir: Path) -> None:
        """Run pending SQL migrations for a module."""
        if not migrations_dir.exists():
            return

        migration_files = sorted(migrations_dir.glob("*.sql"))
        for mf in migration_files:
            version = mf.stem  # e.g. "001_initial"
            existing = await self.fetchone(
                "SELECT 1 FROM applied_migrations WHERE module = ? AND version = ?",
                (module_id, version),
            )
            if existing:
                continue

            logger.info("Running migration %s/%s", module_id, version)
            sql = mf.read_text()
            await self.conn.executescript(sql)
            await self.execute(
                "INSERT INTO applied_migrations (module, version) VALUES (?, ?)",
                (module_id, version),
            )
            await self.commit()
