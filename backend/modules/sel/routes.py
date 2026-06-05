"""System Event Log routes."""

from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from backend.core.i18n import get_lang, t

router = APIRouter()


@router.get("/{server_id}")
async def get_sel(
    server_id: str,
    severity: str | None = None,
    search: str | None = None,
    limit: int = Query(100, le=1000),
):
    import backend.modules as ctx

    conditions = ["server_id = ?"]
    params: list = [server_id]

    if severity:
        conditions.append("severity = ?")
        params.append(severity)
    if search:
        conditions.append("(sensor_name LIKE ? OR description LIKE ? OR event_type LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

    where = " AND ".join(conditions)
    params.append(limit)

    rows = await ctx.db.fetchall(
        f"SELECT * FROM sel_cache WHERE {where} ORDER BY timestamp DESC LIMIT ?",
        tuple(params),
    )
    return {"server_id": server_id, "events": rows, "total": len(rows)}


@router.get("/{server_id}/info")
async def get_sel_info(server_id: str, lang: str = Depends(get_lang)):
    import backend.modules as ctx
    from backend.core.crypto import decrypt
    from backend.main import auth

    server = await ctx.db.fetchone(
        "SELECT host, username_enc, password_enc FROM servers WHERE id = ?", (server_id,)
    )
    if not server:
        return {"success": False, "error": t("server_not_found", lang)}

    key = auth.get_encryption_key()
    try:
        info = await ctx.ipmi.get_sel_info(
            server["host"], decrypt(server["username_enc"], key), decrypt(server["password_enc"], key)
        )
        return {"server_id": server_id, "info": info}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/{server_id}/refresh")
async def refresh_sel(server_id: str, lang: str = Depends(get_lang)):
    """Fetch SEL from BMC and update cache."""
    import backend.modules as ctx
    from backend.core.crypto import decrypt
    from backend.main import auth

    server = await ctx.db.fetchone(
        "SELECT host, username_enc, password_enc FROM servers WHERE id = ?", (server_id,)
    )
    if not server:
        return {"success": False, "error": t("server_not_found", lang)}

    key = auth.get_encryption_key()
    try:
        events = await ctx.ipmi.get_sel(
            server["host"], decrypt(server["username_enc"], key), decrypt(server["password_enc"], key)
        )

        # Clear old cache for this server
        await ctx.db.execute("DELETE FROM sel_cache WHERE server_id = ?", (server_id,))

        # Insert new events
        for ev in events:
            await ctx.db.execute(
                "INSERT INTO sel_cache (server_id, event_id, timestamp, sensor_name, event_type, description, severity) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (server_id, ev.get("event_id"), ev.get("timestamp"), ev.get("sensor_name"),
                 ev.get("event_type"), ev.get("description"), ev.get("severity")),
            )
        await ctx.db.commit()

        return {"success": True, "count": len(events)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/{server_id}/clear")
async def clear_sel(server_id: str, lang: str = Depends(get_lang)):
    import backend.modules as ctx
    from backend.core.crypto import decrypt
    from backend.main import auth

    server = await ctx.db.fetchone(
        "SELECT host, username_enc, password_enc FROM servers WHERE id = ?", (server_id,)
    )
    if not server:
        return {"success": False, "error": t("server_not_found", lang)}

    key = auth.get_encryption_key()
    try:
        await ctx.ipmi.clear_sel(
            server["host"], decrypt(server["username_enc"], key), decrypt(server["password_enc"], key)
        )
        await ctx.db.execute("DELETE FROM sel_cache WHERE server_id = ?", (server_id,))
        await ctx.db.commit()

        await ctx.db.execute(
            "INSERT INTO command_log (server_id, command_type, command_detail, result) VALUES (?, ?, ?, ?)",
            (server_id, "sel_clear", "Cleared SEL", "success"),
        )
        await ctx.db.commit()

        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/{server_id}/export")
async def export_sel(server_id: str, format: str = Query("csv", regex="^(csv|json)$")):
    import backend.modules as ctx

    rows = await ctx.db.fetchall(
        "SELECT event_id, timestamp, sensor_name, event_type, description, severity "
        "FROM sel_cache WHERE server_id = ? ORDER BY timestamp DESC",
        (server_id,),
    )

    if format == "json":
        return StreamingResponse(
            io.BytesIO(json.dumps(rows, indent=2).encode()),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=sel_{server_id[:8]}.json"},
        )

    # CSV
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["event_id", "timestamp", "sensor_name", "event_type", "description", "severity"])
    writer.writeheader()
    writer.writerows(rows)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=sel_{server_id[:8]}.csv"},
    )
