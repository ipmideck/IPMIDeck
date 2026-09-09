"""Data files are created owner-only, and pre-existing loose ones are repaired."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from backend.core.config import save_default_config, update_server_yaml
from backend.core.database import Database

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="POSIX mode bits; Windows takes the ACL path instead"
)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


async def test_fresh_database_and_sidecars_are_owner_only(tmp_path):
    """A new database and the sidecars SQLite derives from it are all 0600."""
    db_path = tmp_path / "ipmideck.db"
    db = Database(str(db_path))
    await db.connect()
    # Force a write so the write-ahead log and shared-memory sidecars materialise.
    await db.execute("INSERT INTO app_config (key, value) VALUES ('probe', '1')")
    await db.commit()
    try:
        assert _mode(db_path) == 0o600
        for sidecar in (f"{db_path}-wal", f"{db_path}-shm"):
            p = Path(sidecar)
            if p.exists():
                assert _mode(p) == 0o600, f"{p.name} is {oct(_mode(p))}"
    finally:
        await db.close()


async def test_existing_loose_database_and_stale_sidecars_are_repaired(tmp_path):
    """An install from an older version heals itself on the next start.

    Sidecars left behind by an abrupt shutdown are reused by SQLite exactly as they
    are, so they have to be fixed explicitly rather than relying on inheritance.
    """
    db_path = tmp_path / "ipmideck.db"
    db = Database(str(db_path))
    await db.connect()
    await db.close()

    # Simulate the pre-existing world-readable install, sidecars included.
    for name in (str(db_path), f"{db_path}-wal", f"{db_path}-shm"):
        Path(name).touch()
        os.chmod(name, 0o644)

    db2 = Database(str(db_path))
    await db2.connect()
    try:
        assert _mode(db_path) == 0o600
        assert _mode(Path(f"{db_path}-wal")) == 0o600
        assert _mode(Path(f"{db_path}-shm")) == 0o600
    finally:
        await db2.close()


def test_default_config_is_written_owner_only(tmp_path):
    path = tmp_path / "config.yaml"
    save_default_config(path)
    assert path.exists()
    assert _mode(path) == 0o600


def test_config_writeback_keeps_it_owner_only(tmp_path):
    """A config file left loose by an older version is tightened when written back."""
    path = tmp_path / "config.yaml"
    save_default_config(path)
    os.chmod(path, 0o644)
    update_server_yaml({"https": True}, config_path=path)
    assert _mode(path) == 0o600
