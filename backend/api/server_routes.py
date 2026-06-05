"""Server (BMC) management routes — CRUD for configured servers."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.core.i18n import get_lang, t

router = APIRouter()


SERVER_COLORS = ["#2563eb", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#6366f1"]


class ServerCreate(BaseModel):
    name: str
    description: str = ""
    host: str
    port: int = 623
    username: str
    password: str
    vendor: str = "dell"
    color: str = ""


class ServerUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    vendor: str | None = None
    color: str | None = None


@router.get("")
async def list_servers():
    from backend.main import db
    servers = await db.fetchall(
        "SELECT id, name, description, host, port, vendor, color, poll_interval, "
        "fanpilot_enabled, is_online, last_seen, created_at FROM servers ORDER BY created_at"
    )
    return {"servers": servers}


@router.post("")
async def create_server(body: ServerCreate):
    from backend.main import db, auth
    from backend.core.crypto import encrypt

    server_id = str(uuid.uuid4())
    key = auth.get_encryption_key()
    username_enc = encrypt(body.username, key)
    password_enc = encrypt(body.password, key)

    # Auto-assign color if not provided
    color = body.color
    if not color:
        count = await db.fetchone("SELECT COUNT(*) as c FROM servers")
        idx = (count["c"] if count else 0) % len(SERVER_COLORS)
        color = SERVER_COLORS[idx]

    await db.execute(
        "INSERT INTO servers (id, name, description, host, port, username_enc, password_enc, vendor, color) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (server_id, body.name, body.description, body.host, body.port, username_enc, password_enc, body.vendor, color),
    )
    await db.commit()
    return {"success": True, "server_id": server_id}


@router.get("/{server_id}")
async def get_server(server_id: str, lang: str = Depends(get_lang)):
    from backend.main import db
    server = await db.fetchone(
        "SELECT id, name, description, host, port, vendor, color, poll_interval, "
        "fanpilot_enabled, is_online, last_seen, created_at FROM servers WHERE id = ?",
        (server_id,),
    )
    if not server:
        return {"success": False, "error": t("server_not_found", lang)}
    return {"server": server}


@router.put("/{server_id}")
async def update_server(server_id: str, body: ServerUpdate, lang: str = Depends(get_lang)):
    from backend.main import db, auth
    from backend.core.crypto import encrypt

    updates = []
    params = []
    for field in ["name", "description", "host", "port", "vendor", "color"]:
        val = getattr(body, field, None)
        if val is not None:
            updates.append(f"{field} = ?")
            params.append(val)

    if body.username is not None:
        key = auth.get_encryption_key()
        updates.append("username_enc = ?")
        params.append(encrypt(body.username, key))

    if body.password is not None:
        key = auth.get_encryption_key()
        updates.append("password_enc = ?")
        params.append(encrypt(body.password, key))

    if not updates:
        return {"success": False, "error": t("no_fields_to_update", lang)}

    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(server_id)
    await db.execute(f"UPDATE servers SET {', '.join(updates)} WHERE id = ?", tuple(params))
    await db.commit()
    return {"success": True}


@router.delete("/{server_id}")
async def delete_server(server_id: str):
    from backend.main import db
    await db.execute("DELETE FROM servers WHERE id = ?", (server_id,))
    await db.commit()
    return {"success": True}


class TestCredentials(BaseModel):
    host: str
    port: int = 623
    username: str
    password: str


@router.post("/test")
async def test_raw_connection(body: TestCredentials):
    """Test IPMI connection with raw credentials (no saved server needed)."""
    from backend.main import ipmi_service

    try:
        status = await ipmi_service.get_power_status(body.host, body.username, body.password)
        return {"success": True, "power_status": status}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/{server_id}/test")
async def test_connection(server_id: str, lang: str = Depends(get_lang)):
    from backend.main import db, auth, ipmi_service
    from backend.core.crypto import decrypt

    server = await db.fetchone(
        "SELECT host, username_enc, password_enc FROM servers WHERE id = ?", (server_id,)
    )
    if not server:
        return {"success": False, "error": t("server_not_found", lang)}

    key = auth.get_encryption_key()
    host = server["host"]
    user = decrypt(server["username_enc"], key)
    pwd = decrypt(server["password_enc"], key)

    try:
        status = await ipmi_service.get_power_status(host, user, pwd)
        await db.execute(
            "UPDATE servers SET is_online = 1, last_seen = CURRENT_TIMESTAMP WHERE id = ?",
            (server_id,),
        )
        await db.commit()
        return {"success": True, "power_status": status}
    except Exception as e:
        await db.execute("UPDATE servers SET is_online = 0 WHERE id = ?", (server_id,))
        await db.commit()
        return {"success": False, "error": str(e)}
