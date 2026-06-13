"""SEL polling loop — broadcasts critical/warning events as alerts (04-W3-01)."""

from __future__ import annotations

import asyncio
import logging

from backend.core.crypto import decrypt
from backend.modules import get_ctx

logger = logging.getLogger("ipmilink.modules.sel")

# Per-server cursor (str keys — Decision C). Initialized from app_config OR sel_cache
# MAX(event_id) on first poll for that server (Decision K — Codex MEDIUM fix: avoid
# replay of old criticals on every restart).
_last_seen_sel_id: dict[str, int] = {}

# slow Dell R720 SEL fetch can exceed the old 15s; 45 is the wait_for backstop. The inner
# LocalIPMIService._exec command_timeout (=30s) is now the effective cap and raises a NAMED,
# message-bearing TimeoutError instead of a blank asyncio.TimeoutError (260613-69x).
_SEL_FETCH_TIMEOUT = 45.0

# Severity classification — map raw SEL severity text to a broadcast severity.
CRITICAL = {"critical", "non-recoverable", "upper non-recoverable", "lower non-recoverable"}
WARNING = {"warning", "non-critical", "upper non-critical", "lower non-critical"}


def _classify(sev_text: str) -> str:
    """Map a raw SEL severity string to one of: critical | warning | info."""
    s = (sev_text or "").lower().strip()
    if s in CRITICAL:
        return "critical"
    if s in WARNING:
        return "warning"
    return "info"


async def _init_cursor(server_id: str) -> int:
    """Initialize the per-server cursor from app_config (preferred) or sel_cache MAX(event_id).

    Decision K: persisting the last-seen event id means old critical/warning events are NOT
    re-broadcast on every backend restart. On a cold start with no persisted cursor we seed
    from the highest event_id already cached for the server, so only genuinely new events fire.
    """
    if server_id in _last_seen_sel_id:
        return _last_seen_sel_id[server_id]
    ctx = get_ctx()  # Fresh lookup — live ctx (Decision J)
    # 1. Try app_config persisted value (Decision K)
    raw = await ctx.db.get_config(f"sel:last_seen_id:{server_id}", default=None)
    if raw is not None:
        try:
            val = int(raw)
            _last_seen_sel_id[server_id] = val
            return val
        except (ValueError, TypeError):
            pass
    # 2. Fallback: MAX(event_id) from sel_cache for this server
    row = await ctx.db.fetchone(
        "SELECT MAX(event_id) AS max_id FROM sel_cache WHERE server_id = ?",
        (server_id,),
    )
    max_id = int(row["max_id"]) if row and row["max_id"] is not None else 0
    _last_seen_sel_id[server_id] = max_id
    return max_id


async def _persist_cursor(server_id: str, last_id: int) -> None:
    """Persist the per-server cursor so restarts don't replay old criticals (Decision K)."""
    _last_seen_sel_id[server_id] = last_id
    ctx = get_ctx()  # Fresh lookup — live ctx (Decision J)
    await ctx.db.set_config(f"sel:last_seen_id:{server_id}", str(last_id))


async def _load_online_servers() -> list[dict]:
    """Read online servers' creds (mirror sensors/tasks.py). Server IDs are str (Decision C)."""
    ctx = get_ctx()  # Fresh lookup — live ctx (Decision J)
    rows = await ctx.db.fetchall(
        "SELECT id, host, username_enc, password_enc FROM servers WHERE is_online = 1"
    )
    if not rows:
        return []
    from backend.main import auth  # AuthManager not in ModuleContext — kept (Decision J)

    key = auth.get_encryption_key()
    out: list[dict] = []
    for r in rows:
        try:
            out.append({
                "id": r["id"],  # str
                "host": r["host"],
                "username": decrypt(r["username_enc"], key),
                "password": decrypt(r["password_enc"], key),
            })
        except Exception:
            logger.exception("failed to decrypt server creds id=%s", r["id"])
    return out


async def _poll_one_server(server: dict) -> None:
    sid: str = server["id"]
    ctx = get_ctx()  # Fresh lookup — live ctx (Decision J)
    try:
        # Decision K — the verified service method is get_sel (the only SEL fetch on the ABC).
        entries = await asyncio.wait_for(
            ctx.ipmi.get_sel(server["host"], server["username"], server["password"]),
            timeout=_SEL_FETCH_TIMEOUT,
        )
    except Exception as e:
        # repr(e) names the exception type so a timeout logs as e.g.
        # TimeoutError('ipmitool timed out after 30s') (or bare TimeoutError()) instead of
        # the blank str() of asyncio.TimeoutError (260613-69x).
        logger.warning("sel poll failed server_id=%s: %s", sid, repr(e))
        return

    last_id = await _init_cursor(sid)
    max_id = last_id
    for ev in entries:
        # Decision K — REAL field names from backend/modules/sel/routes.py:
        # event_id, sensor_name, event_type, description, severity (NOT id/sensor/message).
        eid_raw = ev.get("event_id")
        try:
            eid = int(eid_raw) if eid_raw is not None else 0
        except (ValueError, TypeError):
            continue
        if eid <= last_id:
            continue
        max_id = max(max_id, eid)
        sev = _classify(ev.get("severity", ""))
        if sev in ("critical", "warning"):
            # WebSocketManager.broadcast_alert(server_id, severity, sensor, message, value).
            # SEL field sensor_name -> wire key `sensor`; description -> wire key `message`.
            await ctx.ws.broadcast_alert(
                server_id=sid,
                severity=sev,
                sensor=ev.get("sensor_name", "") or "",
                message=ev.get("description", "") or ev.get("event_type", "") or "",
                value=0,
            )
    if max_id > last_id:
        await _persist_cursor(sid, max_id)


async def sel_polling_loop():
    """Background poll cycle — fetches SEL from each online server and broadcasts new criticals.

    Poll interval reuses a `sel_poll_interval` attr if one is ever added to the IPMI config,
    otherwise falls back to 60s. No new config knob is introduced (CONTEXT 04-W3-01).
    """
    ctx = get_ctx()  # Fresh lookup — live ctx (Decision J)
    poll_interval = getattr(ctx.config.ipmi, "sel_poll_interval", 60)
    logger.info("SEL polling loop started (interval=%ss)", poll_interval)
    while True:
        try:
            servers = await _load_online_servers()
            if servers:
                await asyncio.gather(
                    *(_poll_one_server(s) for s in servers),
                    return_exceptions=True,
                )
            await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            logger.info("SEL polling loop cancelled")
            raise
        except Exception:
            logger.exception("sel_polling_loop iteration failed")
            await asyncio.sleep(poll_interval)
