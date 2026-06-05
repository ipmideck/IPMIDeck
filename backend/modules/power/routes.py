"""Power control routes."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.core.i18n import get_lang, t

router = APIRouter()

# Rate limiting: track last power command per server
_last_command: dict[str, float] = {}
RATE_LIMIT_SECONDS = 5


class PowerAction(BaseModel):
    action: str  # on, soft, off, reset, cycle


@router.get("/{server_id}/status")
async def get_power_status(server_id: str, lang: str = Depends(get_lang)):
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
        status = await ctx.ipmi.get_power_status(
            server["host"], decrypt(server["username_enc"], key), decrypt(server["password_enc"], key)
        )
        return {"server_id": server_id, "status": status}
    except Exception as e:
        return {"server_id": server_id, "status": "unknown", "error": str(e)}


@router.post("/{server_id}/command")
async def power_command(server_id: str, body: PowerAction, lang: str = Depends(get_lang)):
    import backend.modules as ctx
    from backend.core.crypto import decrypt
    from backend.main import auth

    # Rate limit
    now = time.time()
    last = _last_command.get(server_id, 0)
    if now - last < RATE_LIMIT_SECONDS:
        return {"success": False, "error": f"Rate limited — wait {RATE_LIMIT_SECONDS}s between commands"}
    _last_command[server_id] = now

    valid_actions = {"on", "soft", "off", "reset", "cycle"}
    if body.action not in valid_actions:
        return {"success": False, "error": f"Invalid action. Must be one of: {valid_actions}"}

    server = await ctx.db.fetchone(
        "SELECT host, username_enc, password_enc FROM servers WHERE id = ?", (server_id,)
    )
    if not server:
        return {"success": False, "error": t("server_not_found", lang)}

    key = auth.get_encryption_key()
    host = server["host"]
    user = decrypt(server["username_enc"], key)
    pwd = decrypt(server["password_enc"], key)

    try:
        result = await ctx.ipmi.power_command(host, user, pwd, body.action)

        # Log command
        await ctx.db.execute(
            "INSERT INTO command_log (server_id, command_type, command_detail, result) VALUES (?, ?, ?, ?)",
            (server_id, "power", body.action, "success"),
        )
        await ctx.db.commit()

        # Emit event
        await ctx.events.emit("power_state_changed", {
            "server_id": server_id,
            "action": body.action,
        })

        # Broadcast status update
        new_status = "on" if body.action in ("on", "reset", "cycle") else "off"
        await ctx.ws.broadcast_power_status(server_id, new_status)

        return {"success": True, "result": result}
    except Exception as e:
        await ctx.db.execute(
            "INSERT INTO command_log (server_id, command_type, command_detail, result, error_message) VALUES (?, ?, ?, ?, ?)",
            (server_id, "power", body.action, "error", str(e)),
        )
        await ctx.db.commit()
        return {"success": False, "error": str(e)}
