from __future__ import annotations

"""Shared pytest fixtures for the IPMIDeck backend test suite.

Strategy A (lifespan-driven TestClient) for the integration fixtures, plus a Strategy C
(:memory: + manual globals) `auth_manager` fixture for focused crypto/auth unit tests.

WHY env vars are set BEFORE importing `backend.main` (RESEARCH Pitfall 3):
  backend.main.lifespan() calls load_config(), which defaults IPMIDECK_DATA_DIR to ./data on
  Windows and would open the REAL data/ipmideck.db and (non-demo) shell out to ipmitool. Setting
  the temp-DB + demo env via monkeypatch.setenv BEFORE the `from backend.main import app` import
  reroutes the DB into tmp_path and selects DemoIPMIService (no ipmitool, no real BMC).

WHY auth-OFF is done via set_auth_enabled(False) and NOT IPMIDECK_AUTH_ENABLED (REVIEWS HIGH #1):
  IPMIDECK_AUTH_ENABLED only sets config.auth.enabled (config.py). The runtime gate
  require_auth -> AuthManager.is_auth_enabled() reads the DB key `auth_enabled` (auth.py), which
  DEFAULTS to "true" on a fresh temp DB. The env var is INERT for the gate. To genuinely open
  routes the `client` fixture writes the DB config via `bm.auth.set_auth_enabled(False)` AFTER the
  TestClient lifespan has entered (so bm.auth + bm.db are live).

NOTE (REVIEWS MED #11 — lifespan re-mount): each `with TestClient(app)` re-enters lifespan, which
  re-runs module_loader.mount_routes(app, ...) and _mount_spa(app). If backend/static exists this
  appends another SPA catch-all + re-mounts module routes. Integration tests should target static
  `/api/*` routes — they resolve fine even with a duplicated SPA catch-all because /api routes are
  matched before the catch-all. A session-scoped app is not required: demo mode + tmp DB make each
  lifespan cheap.
"""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.main as bm

FIXTURES_DIR = Path(__file__).parent / "fixtures"
IPMI_FIXTURES_DIR = FIXTURES_DIR / "ipmi"


def _set_temp_env(tmp_path, monkeypatch) -> None:
    """Reroute the SQLite DB + config.yaml into a tmp dir and select DemoIPMIService.

    Must be called BEFORE importing/booting the app (Pitfall 3).
    """
    monkeypatch.setenv("IPMIDECK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IPMIDECK_DEMO", "true")
    monkeypatch.setenv("IPMIDECK_DATA_DB_PATH", str(tmp_path / "ipmideck.db"))


@pytest.fixture
def client_auth(tmp_path, monkeypatch):
    """Auth-ON TestClient. auth_enabled defaults to "true" in the fresh temp DB, so guarded
    routes stay protected. This is the genuine guarded-route fixture (401 -> setup -> 200 flow,
    localized login-failure tests) consumed by the integration suite (03-03).
    """
    _set_temp_env(tmp_path, monkeypatch)
    from backend.main import app  # import AFTER env is set (Pitfall 3)

    with TestClient(app) as c:  # __enter__ runs lifespan -> auth initialized, auth_enabled="true"
        yield c


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Auth-OFF TestClient. Auth is disabled by writing the DB config via
    bm.auth.set_auth_enabled(False) AFTER the lifespan has entered (REVIEWS HIGH #1) — the
    IPMIDECK_AUTH_ENABLED env var is INERT for the runtime gate, so it is deliberately NOT used
    to open routes. After this fixture, GET /api/servers returns 200 (not 401).
    """
    _set_temp_env(tmp_path, monkeypatch)
    from backend.main import app  # import AFTER env is set (Pitfall 3)

    with TestClient(app) as c:  # lifespan has run; bm.auth + bm.db are live
        # set_auth_enabled is async and this fixture is sync; drive the coroutine on the loop.
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("event loop closed")
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        loop.run_until_complete(bm.auth.set_auth_enabled(False))
        yield c


@pytest.fixture
async def auth_manager(tmp_path):
    """Strategy C: a tmp-dir AuthManager + Database for focused auth/crypto unit tests.

    No lifespan, no module loading, no background tasks — just a connected on-disk DB inside
    pytest's per-test tmp_path and an initialized AuthManager. Yields (am, db); closes on teardown.

    NOTE (04-W4-04): the DB lives in tmp_path (NOT ":memory:") on purpose —
    AuthManager.initialize() derives its data_dir from Path(db.db_path).parent and writes the
    file-based encryption.key there. A ":memory:" DB would resolve the parent to the repo root and
    leak the key file into the working tree. tmp_path keeps it isolated and auto-cleaned.
    """
    from backend.core.auth import AuthManager
    from backend.core.database import Database

    db = Database(str(tmp_path / "ipmideck.db"))
    await db.connect()
    am = AuthManager(db)
    await am.initialize()
    try:
        yield am, db
    finally:
        await db.close()
