"""Server (BMC) management routes — CRUD for configured servers."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.core.i18n import get_lang, t

router = APIRouter()


# 08-01 D-01/D-12: the canonical six-value vendor vocabulary. As a Pydantic Literal on the
# request models, ANY other string is rejected at the PARSE layer with an automatic HTTP 422
# (before the handler body runs), closing the "garbage vendor string reaches dispatch" class
# and retiring the legacy 'hp' value (normalized to 'hpe' by the database.py D-02 migration).
Vendor = Literal["dell", "supermicro", "hpe", "lenovo", "ibm", "generic"]


SERVER_COLORS = ["#2563eb", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#6366f1"]


def _validate_host(host: str) -> bool:
    """Return True if `host` is a bare hostname or IP literal usable as ipmitool's -H arg.

    Catches the URL / garbage class of mistake (scheme, embedded :port, path/slash,
    whitespace) — NOT a full RFC validator. ipmitool's -H wants a bare host, so anything
    a user would paste as a URL is rejected here instead of failing later in the poll loop.

    IPv6 DECISION: only the BRACKETED form `[..::..]` is accepted (the standard way to
    write an IPv6 literal where a port could follow). A bare unbracketed IPv6 (with its
    internal colons) is rejected by the colon rule below — bracket it to use IPv6.
    """
    h = host.strip()
    if not h:
        return False
    # Whitespace anywhere -> invalid.
    if any(ch.isspace() for ch in h):
        return False
    # URL scheme (http://, https://, anything with "://").
    if "://" in h:
        return False
    # Path / slash.
    if "/" in h or "\\" in h:
        return False
    # Bracketed IPv6 literal: accept `[...]` outright (do NOT trip the colon rule).
    if h.startswith("[") and h.endswith("]") and ":" in h[1:-1]:
        return True
    # Embedded port or stray colon (host:623 belongs in the separate `port` field).
    if ":" in h:
        return False
    return True


class ServerCreate(BaseModel):
    name: str
    description: str = ""
    host: str
    port: int = 623
    username: str
    password: str
    vendor: Vendor = "dell"
    color: str = ""
    # 04-W2-02: per-server energy tariff (€/kWh, USD/kWh, etc.). NULL = not configured.
    cost_per_kwh: float | None = None


class ServerUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    # 08-01 Pitfall 8: keep vendor OPTIONAL so a PUT that omits it leaves the column
    # unchanged (exclude_unset). Only a NON-null INVALID value trips the Literal -> 422.
    vendor: Vendor | None = None
    color: str | None = None
    # 04-W2-02: per-server energy tariff. Explicit null clears; omitted leaves unchanged
    # (handled via model_dump(exclude_unset=True) in update_server).
    cost_per_kwh: float | None = None


@router.get("")
async def list_servers():
    from backend.main import db
    servers = await db.fetchall(
        "SELECT id, name, description, host, port, vendor, color, poll_interval, "
        "fanpilot_enabled, is_online, last_seen, cost_per_kwh, created_at "
        "FROM servers ORDER BY created_at"
    )
    return {"servers": servers}


@router.post("")
async def create_server(body: ServerCreate, lang: str = Depends(get_lang)):
    from backend.main import db, auth
    from backend.core.crypto import encrypt

    # Reject a URL / garbage host (scheme, embedded :port, path/slash, whitespace) BEFORE
    # the INSERT so it never reaches ipmitool's -H flag in the background poll loops.
    if not _validate_host(body.host):
        return {"success": False, "error": t("invalid_host", lang)}

    # 04-W2-02: light validation on the tariff field. Negative values are nonsense;
    # 0.0 is allowed (hypothetical free electricity); null = not configured.
    if body.cost_per_kwh is not None and body.cost_per_kwh < 0:
        return {"success": False, "error": "cost_per_kwh_negative"}

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
        "INSERT INTO servers (id, name, description, host, port, username_enc, password_enc, "
        "vendor, color, cost_per_kwh) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            server_id, body.name, body.description, body.host, body.port,
            username_enc, password_enc, body.vendor, color, body.cost_per_kwh,
        ),
    )
    await db.commit()
    return {"success": True, "server_id": server_id}


@router.get("/{server_id}")
async def get_server(server_id: str, lang: str = Depends(get_lang)):
    from backend.main import db
    server = await db.fetchone(
        "SELECT id, name, description, host, port, vendor, color, poll_interval, "
        "fanpilot_enabled, is_online, last_seen, cost_per_kwh, created_at "
        "FROM servers WHERE id = ?",
        (server_id,),
    )
    if not server:
        return {"success": False, "error": t("server_not_found", lang)}
    return {"server": server}


@router.put("/{server_id}")
async def update_server(server_id: str, body: ServerUpdate, lang: str = Depends(get_lang)):
    from backend.main import db, auth
    from backend.core.crypto import encrypt

    # 04-W2-02: payload tracking. model_dump(exclude_unset=True) preserves the
    # explicit-vs-omitted distinction so the frontend can set cost_per_kwh = null
    # (clear tariff) OR set it to 0.0 OR omit it entirely (leave unchanged).
    payload = body.model_dump(exclude_unset=True)

    # 04-W2-02: light validation on the tariff field.
    if "cost_per_kwh" in payload and payload["cost_per_kwh"] is not None and payload["cost_per_kwh"] < 0:
        return {"success": False, "error": "cost_per_kwh_negative"}

    # Validate host ONLY when explicitly provided (exclude_unset semantics): a PUT that
    # omits `host` leaves the column untouched and is never blocked by this guard.
    if "host" in payload and not _validate_host(payload["host"]):
        return {"success": False, "error": t("invalid_host", lang)}

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

    # 04-W2-02 (Decision E + omitted-vs-null): only touch cost_per_kwh if the key
    # was EXPLICITLY in the request body. Frontend always sends it (including null)
    # from the Edit Server save handler; legacy callers that omit the field leave
    # the column unchanged.
    if "cost_per_kwh" in payload:
        updates.append("cost_per_kwh = ?")
        params.append(payload["cost_per_kwh"])  # may be None — clears the tariff

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
