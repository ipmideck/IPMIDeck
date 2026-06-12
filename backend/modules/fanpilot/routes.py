"""FanPilot routes — profiles CRUD, mode control, status."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.core.i18n import get_lang, t
from backend.modules import get_ctx
from backend.modules.fanpilot.tasks import get_last_state, set_last_state, wake_loop
from backend.modules.sensors.tasks import wake_loop as wake_sensor_loop

router = APIRouter()


class ProfileCreate(BaseModel):
    name: str
    description: str = ""
    curve_points: list[dict]
    interpolation: str = "linear"
    hysteresis: float = 3.0
    safety_threshold: float = 85.0
    source_sensor: str = "CPU Temp"


class ProfileUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    curve_points: list[dict] | None = None
    interpolation: str | None = None
    hysteresis: float | None = None
    safety_threshold: float | None = None
    source_sensor: str | None = None


class FanMode(BaseModel):
    """Mode change request. ``manual_speed`` is also accepted as ``speed`` (the JS
    client sends the latter) — see ``populate_by_name`` + ``Field(alias=...)``."""

    model_config = {"populate_by_name": True}

    mode: str  # auto, manual, fanpilot
    profile_id: int | None = None
    manual_speed: int | None = Field(default=None, alias="speed")


# === Profiles ===

@router.get("/profiles")
async def list_profiles():
    ctx = get_ctx()  # Fresh lookup — live ctx (Decision J)
    rows = await ctx.db.fetchall("SELECT * FROM fan_profiles ORDER BY is_preset DESC, name")
    for row in rows:
        row["curve_points"] = json.loads(row["curve_points"])
    return {"profiles": rows}


@router.post("/profiles")
async def create_profile(body: ProfileCreate):
    ctx = get_ctx()  # Fresh lookup — live ctx (Decision J)
    await ctx.db.execute(
        "INSERT INTO fan_profiles (name, description, curve_points, interpolation, hysteresis, safety_threshold, source_sensor) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (body.name, body.description, json.dumps(body.curve_points), body.interpolation,
         body.hysteresis, body.safety_threshold, body.source_sensor),
    )
    await ctx.db.commit()
    row = await ctx.db.fetchone("SELECT last_insert_rowid() as id")
    return {"success": True, "profile_id": row["id"]}


@router.get("/profiles/{profile_id}")
async def get_profile(profile_id: int, lang: str = Depends(get_lang)):
    ctx = get_ctx()  # Fresh lookup — live ctx (Decision J)
    row = await ctx.db.fetchone("SELECT * FROM fan_profiles WHERE id = ?", (profile_id,))
    if not row:
        return {"success": False, "error": t("profile_not_found", lang)}
    row["curve_points"] = json.loads(row["curve_points"])
    return {"profile": row}


@router.put("/profiles/{profile_id}")
async def update_profile(profile_id: int, body: ProfileUpdate, lang: str = Depends(get_lang)):
    ctx = get_ctx()  # Fresh lookup — live ctx (Decision J)
    existing = await ctx.db.fetchone("SELECT is_preset FROM fan_profiles WHERE id = ?", (profile_id,))
    if not existing:
        return {"success": False, "error": t("profile_not_found", lang)}

    updates = []
    params = []
    for field in ["name", "description", "interpolation", "hysteresis", "safety_threshold", "source_sensor"]:
        val = getattr(body, field, None)
        if val is not None:
            updates.append(f"{field} = ?")
            params.append(val)

    if body.curve_points is not None:
        updates.append("curve_points = ?")
        params.append(json.dumps(body.curve_points))

    if not updates:
        return {"success": False, "error": t("no_fields_to_update", lang)}

    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(profile_id)
    await ctx.db.execute(f"UPDATE fan_profiles SET {', '.join(updates)} WHERE id = ?", tuple(params))
    await ctx.db.commit()
    # Wake the loop so any server currently running this profile applies the new
    # curve/hysteresis/safety within ~1s instead of waiting up to 30s. Also wake the
    # sensor loop so the resulting RPM change reaches the UI within ~5s instead of
    # up to one poll interval.
    wake_loop()
    wake_sensor_loop()
    return {"success": True}


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: int, lang: str = Depends(get_lang)):
    ctx = get_ctx()  # Fresh lookup — live ctx (Decision J)
    existing = await ctx.db.fetchone("SELECT is_preset FROM fan_profiles WHERE id = ?", (profile_id,))
    if not existing:
        return {"success": False, "error": t("profile_not_found", lang)}
    if existing["is_preset"]:
        return {"success": False, "error": t("cannot_delete_preset", lang)}
    await ctx.db.execute("DELETE FROM fan_profiles WHERE id = ?", (profile_id,))
    await ctx.db.commit()
    return {"success": True}


# === Server FanPilot control ===

@router.get("/{server_id}/status")
async def get_fanpilot_status(server_id: str, lang: str = Depends(get_lang)):
    ctx = get_ctx()  # Fresh lookup — live ctx (Decision J)
    server = await ctx.db.fetchone(
        "SELECT fanpilot_enabled, fanpilot_profile_id FROM servers WHERE id = ?", (server_id,)
    )
    if not server:
        return {"success": False, "error": t("server_not_found", lang)}

    profile = None
    if server["fanpilot_profile_id"]:
        profile = await ctx.db.fetchone(
            "SELECT id, name FROM fan_profiles WHERE id = ?", (server["fanpilot_profile_id"],)
        )

    # In-memory state: written by the loop, the recovery path, and the mode-change
    # route. Cold-start fallback: if the cache is at its default but the DB says
    # FanPilot is enabled, trust the DB (the loop will refresh `speed_pct` shortly).
    cached = get_last_state(server_id)
    mode = cached["mode"]
    if mode == "auto" and server["fanpilot_enabled"]:
        mode = "fanpilot"

    return {
        "server_id": server_id,
        "enabled": bool(server["fanpilot_enabled"]),
        "profile": profile,
        "mode": mode,
        "current_speed_pct": cached["speed_pct"],
    }


@router.post("/{server_id}/mode")
async def set_fanpilot_mode(server_id: str, body: FanMode, lang: str = Depends(get_lang)):
    from backend.core.crypto import decrypt
    from backend.main import auth  # AuthManager not in ModuleContext — kept (Decision J)

    ctx = get_ctx()  # Fresh lookup — live ctx (Decision J)
    server = await ctx.db.fetchone(
        "SELECT host, username_enc, password_enc, vendor FROM servers WHERE id = ?",
        (server_id,),
    )
    if not server:
        return {"success": False, "error": t("server_not_found", lang)}

    key = auth.get_encryption_key()
    host = server["host"]
    user = decrypt(server["username_enc"], key)
    pwd = decrypt(server["password_enc"], key)
    # 04-W4-02: vendor-aware dispatch (default 'dell' if NULL/empty — Decision G).
    vendor = server["vendor"] or "dell"

    if body.mode == "auto":
        await ctx.ipmi.set_fan_mode(host, user, pwd, manual=False, vendor=vendor)
        await ctx.db.execute(
            "UPDATE servers SET fanpilot_enabled = 0 WHERE id = ?", (server_id,)
        )
        set_last_state(server_id, "auto")
    elif body.mode == "manual":
        speed = body.manual_speed if body.manual_speed is not None else 50
        await ctx.ipmi.set_fan_mode(host, user, pwd, manual=True, vendor=vendor)
        await ctx.ipmi.set_fan_speed(host, user, pwd, speed, vendor=vendor)
        await ctx.db.execute(
            "UPDATE servers SET fanpilot_enabled = 0 WHERE id = ?", (server_id,)
        )
        set_last_state(server_id, "manual", speed)
    elif body.mode == "fanpilot":
        profile_id = body.profile_id
        if not profile_id:
            return {"success": False, "error": t("profile_id_required", lang)}
        await ctx.db.execute(
            "UPDATE servers SET fanpilot_enabled = 1, fanpilot_profile_id = ? WHERE id = ?",
            (profile_id, server_id),
        )
        # The loop will overwrite `speed_pct` on its first tick; until then the UI
        # shows '--' which is honest (we don't know yet).
        set_last_state(server_id, "fanpilot")
        # Wake the loop so the first tick happens within ~1s instead of up to 30s.
        wake_loop()
    else:
        return {"success": False, "error": f"Invalid mode: {body.mode}"}

    await ctx.db.commit()
    # All three valid modes (auto/manual/fanpilot) change fan state on the BMC,
    # so wake the sensor loop to read back the new RPMs within ~5s instead of
    # waiting up to one poll interval.
    wake_sensor_loop()

    # Log
    await ctx.db.execute(
        "INSERT INTO command_log (server_id, command_type, command_detail, result) VALUES (?, ?, ?, ?)",
        (server_id, "fan_mode", body.mode, "success"),
    )
    await ctx.db.commit()

    return {"success": True, "mode": body.mode}
