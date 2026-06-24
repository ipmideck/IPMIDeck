"""System routes — health, config, command log, app-config key/value."""

from __future__ import annotations

import csv
import io
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.core.auth import require_auth

router = APIRouter()


# 04-W1-01 (Plan 04-01, Task 2): generic app_config K/V endpoints.
# Mounted at prefix="/api" (see backend/main.py:159), so the route paths
# below resolve to /api/system/app-config/{key} (Decision B).
# Uses current globals pattern (Decision A1): `from backend.main import db`
# inside the handler body — no app.state.bm container exists in this repo.

class AppConfigValueBody(BaseModel):
    """PUT body for app-config endpoint. Bool / str / float / null accepted."""
    value: bool | str | float | None


# Allow-list of writable app_config keys. Prevents the endpoint from being
# abused to write arbitrary config rows. Extend in later plans as new
# Settings cards land (Plan 04 alerting toggle, Plan 05 retention days,
# Plan 02 currency).
_ALLOWED_APP_CONFIG_KEYS = {
    "fanpilot.auto_recover_on_offline",
    "currency",
    "alerting.notifications_enabled",
    "data.retention_days",
}


@router.get("/system/app-config/{key}", dependencies=[Depends(require_auth)])
async def get_app_config_value(key: str):
    """Read a single app_config value. Returns {success, key, value}.

    Bool-shaped storage convention: values stored as 'true'/'false' strings are
    coerced back to JSON booleans in the response so the frontend can use
    them directly. Missing rows return value=None (not an error).
    """
    from backend.main import db
    raw = await db.get_config(key, default=None)
    if raw is None:
        return {"success": True, "key": key, "value": None}
    # Bool-shaped values stored as 'true'/'false'
    if isinstance(raw, str) and raw.lower() in ("true", "false"):
        return {"success": True, "key": key, "value": raw.lower() == "true"}
    return {"success": True, "key": key, "value": raw}


@router.put("/system/app-config/{key}", dependencies=[Depends(require_auth)])
async def put_app_config_value(key: str, body: AppConfigValueBody):
    """Write a single app_config value. Key must be in the allow-list.

    Booleans are coerced to 'true'/'false' strings (Phase 1 convention used by
    auth_enabled). None becomes empty string. Everything else is str()'d.
    """
    if key not in _ALLOWED_APP_CONFIG_KEYS:
        return {"success": False, "error": "key_not_allowed"}
    from backend.main import db
    v = body.value
    if isinstance(v, bool):
        stored = "true" if v else "false"
    elif v is None:
        stored = ""
    else:
        stored = str(v)
    await db.set_config(key, stored)
    return {"success": True, "key": key, "value": body.value}


# 04-W2-07 (Plan 04-04, Task 2): energy-counter reset endpoints.
# Mounted at prefix="/api" so paths resolve to /api/system/energy-reset[s]
# (Decision B). Current-globals pattern (Decision A1). Server IDs are strings
# (Decision C). The reset timestamp per server is persisted in app_config under
# the key energy_reset:{server_id}; the frontend integrator (usePowerStats) zeros
# itself when that timestamp changes.


class EnergyResetBody(BaseModel):
    """POST body. server_id=None means "all servers" (Decision C — str not int)."""
    server_id: str | None = None


@router.post("/system/energy-reset", dependencies=[Depends(require_auth)])
async def energy_reset(body: EnergyResetBody):
    """Reset energy counters for one server or all servers.

    Returns the list of affected server_id strings so the frontend resetAll()
    can merge against the AUTHORITATIVE affected set, not just keys already in its
    local map (Decision P — Codex MEDIUM fix).
    """
    from backend.main import db

    now_iso = datetime.now(timezone.utc).isoformat()
    if body.server_id is None:
        rows = await db.fetchall("SELECT id FROM servers")
        affected_ids = [r["id"] for r in rows]  # list[str] — Decision C
        for sid in affected_ids:
            await db.set_config(f"energy_reset:{sid}", now_iso)
        return {
            "success": True,
            "count": len(affected_ids),
            "affected_ids": affected_ids,
            "timestamp": now_iso,
        }
    await db.set_config(f"energy_reset:{body.server_id}", now_iso)
    return {
        "success": True,
        "server_id": body.server_id,
        "affected_ids": [body.server_id],
        "timestamp": now_iso,
    }


@router.get("/system/energy-resets", dependencies=[Depends(require_auth)])
async def energy_resets():
    """Return {server_id: iso_timestamp_or_null} for all servers."""
    from backend.main import db

    rows = await db.fetchall("SELECT id FROM servers")
    out: dict[str, str | None] = {}
    for r in rows:
        out[r["id"]] = await db.get_config(f"energy_reset:{r['id']}", default=None)
    return {"success": True, "resets": out}


# 04-W5-01 (Plan 04-08, Task 1): data-retention UI endpoints.
# Mounted at prefix="/api" so paths resolve to /api/system/db-stats,
# /api/system/retention-days, /api/system/retention-cleanup-now (Decision B).
# Current-globals pattern (Decision A1: `from backend.main import db, config`).
# Retention preference is persisted in app_config under "data.retention_days"
# (RESEARCH Pitfall 8 — avoid YAML comment stomping); the cleanup loop reads from
# app_config first, falling back to config.data.retention_days. All require auth.


class RetentionBody(BaseModel):
    """PUT body for /system/retention-days. Range-checked 7..365 in the handler."""
    days: int


@router.get("/system/db-stats", dependencies=[Depends(require_auth)])
async def db_stats():
    """Return DB file size + sensor_readings row count + oldest reading timestamp."""
    from pathlib import Path

    from backend.main import config, db

    db_path = Path(config.data.db_path)
    db_size_bytes = db_path.stat().st_size if db_path.exists() else 0
    rows_result = await db.fetchone("SELECT COUNT(*) AS n FROM sensor_readings")
    rows = rows_result["n"] if rows_result else 0
    oldest_result = await db.fetchone("SELECT MIN(timestamp) AS ts FROM sensor_readings")
    oldest = oldest_result["ts"] if oldest_result and oldest_result["ts"] else None
    return {
        "success": True,
        "db_size_bytes": db_size_bytes,
        "sensor_readings_rows": rows,
        "oldest_reading_timestamp": oldest,
    }


@router.get("/system/retention-days", dependencies=[Depends(require_auth)])
async def get_retention_days():
    """Read the effective retention window — app_config override or config default."""
    from backend.main import config, db

    override = await db.get_config("data.retention_days", default=None)
    days = int(override) if override else int(config.data.retention_days)
    return {"success": True, "days": days}


@router.put("/system/retention-days", dependencies=[Depends(require_auth)])
async def put_retention_days(body: RetentionBody):
    """Persist the retention window to app_config (preferred over YAML — Pitfall 8)."""
    if body.days < 7 or body.days > 365:
        return {"success": False, "error": "out_of_range"}
    from backend.main import db

    await db.set_config("data.retention_days", str(body.days))
    return {"success": True, "days": body.days}


@router.post("/system/retention-cleanup-now", dependencies=[Depends(require_auth)])
async def retention_cleanup_now():
    """Trigger the shared retention cleanup pass immediately. Returns rows deleted."""
    from backend.main import config, db
    from backend.modules.sensors.tasks import retention_cleanup_once

    deleted = await retention_cleanup_once(db, config)
    return {"success": True, "deleted_rows": deleted}


# 04-W4-03 (Plan 04-07): HTTPS/cert management. Routes use the /system/ prefix
# (Decision B → /api/system/...) and current globals (Decision A1: `from backend.main
# import config`). YAML writeback via config.update_server_yaml (full read-mutate-dump;
# comment-stripping tradeoff accepted per RESEARCH Pitfall 8). Both require auth.


class HttpsBody(BaseModel):
    """PUT body for /system/https — flips the persisted HTTPS toggle."""
    https: bool


@router.post("/system/gen-cert", dependencies=[Depends(require_auth)])
async def gen_cert():
    """Generate a self-signed cert+key under data/certs/, persist the paths to config.yaml.

    Returns {success, cert_path, key_path}. HTTPS still requires server.https=true + a
    restart to take effect (the cookie secure flag and uvicorn TLS bind both read it).
    """
    from pathlib import Path

    from backend.core.certs import generate_self_signed
    from backend.core.config import update_server_yaml
    from backend.main import config

    try:
        cert_dir = Path(config.data.db_path).parent / "certs"
        cert_path, key_path = generate_self_signed(cert_dir)
        update_server_yaml({"cert_file": str(cert_path), "key_file": str(key_path)})
        # Reflect in the in-memory config so a later https toggle persists the paths too.
        config.server.cert_file = str(cert_path)
        config.server.key_file = str(key_path)
        return {"success": True, "cert_path": str(cert_path), "key_path": str(key_path)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.put("/system/https", dependencies=[Depends(require_auth)])
async def toggle_https(body: HttpsBody):
    """Persist the HTTPS on/off toggle to config.yaml. Requires a restart to take effect."""
    from backend.core.config import update_server_yaml
    from backend.main import config

    try:
        update_server_yaml({"https": body.https})
        config.server.https = body.https  # in-memory mirror; bind/cookie read it at boot
        return {"success": True, "https": body.https, "restart_required": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


# 04-W6-03 (Plan 04-09): Backup / Restore / CSV export.
# Mounted at prefix="/api" so paths resolve to /api/system/backup, /api/system/restore,
# /api/system/history-csv (Decision B). Current-globals pattern (Decision A1:
# `from backend.main import config, db`). Server IDs are strings (Decision C).
#
# Backup zip MUST include data/encryption.key — Plan 04-07 moved the at-rest
# credential key OUT of the DB into that file. A backup without it makes the
# restored BMC credentials undecryptable (04-07-SUMMARY warning). The data dir is
# derived the same way AuthManager derives it: Path(config.data.db_path).parent.

# Backups WRITE and RESTORE the "ipmideck.db" arcname. The DB is the only required
# member of a backup zip; config.yaml and encryption.key are optional.
_DB_BACKUP_ARCNAMES = {"ipmideck.db"}
ALLOWED_BACKUP_FILES = {"ipmideck.db", "config.yaml", "encryption.key"}


@router.post("/system/backup", dependencies=[Depends(require_auth)])
async def backup():
    """Stream a .zip of ipmideck.db + config.yaml + encryption.key for download.

    encryption.key is REQUIRED (04-W4-04): without it the restored credentials
    cannot be decrypted. The data dir is the parent of config.data.db_path.
    """
    from backend.main import config, db

    data_dir = Path(config.data.db_path).parent
    db_path = Path(config.data.db_path)
    config_path = data_dir / "config.yaml"
    key_path = data_dir / "encryption.key"

    # The DB runs in WAL mode (PRAGMA journal_mode=WAL) — recent committed writes
    # may still live in ipmideck.db-wal, NOT the main ipmideck.db file. Checkpoint
    # (TRUNCATE) first so the zipped ipmideck.db is a COMPLETE, consistent snapshot;
    # otherwise a restored backup silently loses any not-yet-checkpointed rows.
    try:
        await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        await db.commit()
    except Exception:
        pass  # best-effort — a backup of the main file alone is still better than failing

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if db_path.exists():
            z.write(db_path, arcname="ipmideck.db")
        if config_path.exists():
            z.write(config_path, arcname="config.yaml")
        if key_path.exists():
            z.write(key_path, arcname="encryption.key")
    buf.seek(0)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="ipmideck-backup-{ts}.zip"'},
    )


@router.post("/system/restore", dependencies=[Depends(require_auth)])
async def restore(request: Request):
    """Validate an uploaded backup zip and stage it for an atomic swap on next startup.

    The zip arrives as the RAW request body (Content-Type: application/zip) — NOT a
    multipart form — so we don't pull in the python-multipart dependency (the repo
    ships only the deps in pyproject.toml; "no new dependencies" is a phase constraint).
    The zip is extracted ONLY into data/staging/ — the live files are never touched
    here. lifespan() applies the swap on the next boot via _apply_staging_if_present.
    Zip-slip guarded by an exact-filename allow-list (reject any path separators).
    """
    from backend.main import config

    data_dir = Path(config.data.db_path).parent
    staging = data_dir / "staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    content = await request.body()
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            names = z.namelist()
            for name in names:
                # Zip-slip guard: only allow our exact filenames; reject traversal.
                if name not in ALLOWED_BACKUP_FILES or "/" in name or "\\" in name:
                    shutil.rmtree(staging, ignore_errors=True)
                    return {"success": False, "error": "unexpected_file_in_zip", "name": name}
            # A valid backup must at least contain the DB ("ipmideck.db" arcname);
            # missing_database when it is absent.
            if not _DB_BACKUP_ARCNAMES.intersection(names):
                shutil.rmtree(staging, ignore_errors=True)
                return {"success": False, "error": "missing_database"}
            for name in names:
                z.extract(name, staging)
    except zipfile.BadZipFile:
        shutil.rmtree(staging, ignore_errors=True)
        return {"success": False, "error": "invalid_zip"}

    return {
        "success": True,
        "restart_required": True,
        "message": "Backup uploaded. Restart the app to apply.",
    }


async def _apply_staging_if_present(config) -> bool:
    """Apply a pending restore by atomic file swap. Called from lifespan() on startup.

    Moves each staged file into the data dir, replacing the live copy, then removes
    the staging dir. Returns True if a swap was applied. Runs BEFORE Database.connect()
    so the new ipmideck.db is the one that gets opened.

    The staged DB carries the "ipmideck.db" arcname and lands at the CONFIGURED db
    filename (db_name) so a non-default db_path still restores correctly.

    CRITICAL (WAL): the DB runs in WAL mode, so the data dir may hold an orphaned
    <db>-wal / <db>-shm from the pre-restore process. If we drop in the restored DB
    but leave those stale sidecars, SQLite's WAL recovery on next open mixes the OLD
    wal frames with the NEW db file → the restore silently shows the wrong (or empty)
    data. We must delete the sidecars whenever we replace the DB.
    """
    data_dir = Path(config.data.db_path).parent
    staging = data_dir / "staging"
    if not staging.exists():
        return False
    db_name = Path(config.data.db_path).name
    for name in ALLOWED_BACKUP_FILES:
        src = staging / name
        if src.exists():
            # The DB arcname is "ipmideck.db"; land it at the CONFIGURED db filename so
            # a non-default db_path restores correctly.
            is_db = name in _DB_BACKUP_ARCNAMES
            dest = (data_dir / db_name) if is_db else (data_dir / name)
            # When replacing the DB, also remove any orphaned WAL/SHM sidecars of the
            # DESTINATION file so the restored DB opens clean (the backup zip only
            # carries the checkpointed main file — its own sidecars don't exist).
            if is_db:
                for sidecar in (f"{db_name}-wal", f"{db_name}-shm"):
                    sc = data_dir / sidecar
                    if sc.exists():
                        sc.unlink()
            shutil.move(str(src), str(dest))
    shutil.rmtree(staging, ignore_errors=True)
    return True


# CSV history export. The `range` values MATCH the frontend useRangeStore enum
# ("live" | "1h" | "24h" | "7d") — NOT the day/week names in the plan snippet.
# The actual store (frontend/src/stores/range-store.ts) uses 1h/24h/7d, so this
# mapping is the correct one (Codex MEDIUM concern: match useRangeStore enum).
# Values are SQLite datetime() offsets, mirroring sensors/routes.py get_sensor_history
# so the cutoff is in the SAME 'YYYY-MM-DD HH:MM:SS' format as the stored timestamps
# (a Python isoformat() cutoff with a 'T' separator would never match — space < 'T').
_RANGE_OFFSETS = {
    "live": "-5 minutes",
    "1h": "-1 hour",
    "24h": "-24 hours",
    "7d": "-7 days",
}


@router.get("/system/history-csv", dependencies=[Depends(require_auth)])
async def history_csv(server_id: str, sensor_name: str, range: str = "24h"):
    """Export sensor history as CSV. server_id is str (Decision C); range matches
    useRangeStore ("live" | "1h" | "24h" | "7d")."""
    from backend.main import db

    offset = _RANGE_OFFSETS.get(range, _RANGE_OFFSETS["24h"])
    rows = await db.fetchall(
        "SELECT timestamp, sensor_name, value FROM sensor_readings "
        "WHERE server_id = ? AND sensor_name = ? AND timestamp > datetime('now', ?) "
        "ORDER BY timestamp ASC",
        (server_id, sensor_name, offset),
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["timestamp", "sensor_name", "value"])
    for r in rows:
        writer.writerow([r["timestamp"], r["sensor_name"], r["value"]])
    safe = sensor_name.replace(" ", "_").replace("/", "_")
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="ipmideck-{safe}-{range}.csv"'},
    )


@router.get("/health")
async def health():
    from backend.core.branding import VERSION
    from backend.main import config, ws_manager, module_loader
    return {
        "status": "ok",
        "version": VERSION,
        "demo": config.demo,
        "websocket_connections": ws_manager.connection_count,
        "modules_loaded": len(module_loader.get_enabled_modules()),
        "time": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/config", dependencies=[Depends(require_auth)])
async def get_config():
    from backend.main import config
    return {
        "server": {"host": config.server.host, "port": config.server.port},
        "ipmi": {"poll_interval": config.ipmi.poll_interval},
        "data": {"retention_days": config.data.retention_days},
        "demo": config.demo,
    }


@router.get("/logs", dependencies=[Depends(require_auth)])
async def get_command_log(limit: int = 50, server_id: str | None = None):
    from backend.main import db
    if server_id:
        rows = await db.fetchall(
            "SELECT * FROM command_log WHERE server_id = ? ORDER BY timestamp DESC LIMIT ?",
            (server_id, limit),
        )
    else:
        rows = await db.fetchall(
            "SELECT * FROM command_log ORDER BY timestamp DESC LIMIT ?", (limit,)
        )
    return {"logs": rows}


@router.get("/search", dependencies=[Depends(require_auth)])
async def search(q: str):
    """Global search for command palette — searches servers, sensors, actions."""
    from backend.main import db, module_loader

    results = []

    # Search servers
    servers = await db.fetchall(
        "SELECT id, name, host, vendor FROM servers WHERE name LIKE ? OR host LIKE ? LIMIT 5",
        (f"%{q}%", f"%{q}%"),
    )
    for s in servers:
        results.append({"type": "server", "label": s["name"], "sublabel": s["host"], "id": s["id"]})

    # Search pages
    pages = [
        {"label": "Dashboard", "path": "/"},
        {"label": "FanPilot", "path": "/fanpilot"},
        {"label": "Event Log", "path": "/sel"},
        {"label": "Hardware", "path": "/fru"},
        {"label": "Modules", "path": "/modules"},
        {"label": "Settings", "path": "/settings"},
    ]
    for p in pages:
        if q.lower() in p["label"].lower():
            results.append({"type": "page", "label": p["label"], "path": p["path"]})

    # Search modules
    for mod in module_loader.get_all_modules():
        if q.lower() in mod.name.lower():
            results.append({"type": "module", "label": mod.name, "id": mod.id})

    return {"results": results}
