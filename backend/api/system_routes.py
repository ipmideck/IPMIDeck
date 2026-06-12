"""System routes — health, config, command log, app-config key/value."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
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


@router.get("/health")
async def health():
    from backend.main import config, ws_manager, module_loader
    return {
        "status": "ok",
        "version": "2.0.0-alpha.1",
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
