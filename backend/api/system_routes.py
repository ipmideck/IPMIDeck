"""System routes — health, config, command log."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends

from backend.core.auth import require_auth

router = APIRouter()


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
