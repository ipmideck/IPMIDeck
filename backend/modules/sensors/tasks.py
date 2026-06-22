"""Sensor polling background task — reads all BMC sensors and broadcasts via WebSocket."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger("ipmideck.modules.sensors")

_running = True

# Non-blocking per-server cooldown: server_id -> monotonic ts before which we skip polling.
# A server that times out / errors is placed on this cooldown so we do not re-hit a known-offline
# BMC on every poll cycle. This is a SKIP GATE consulted by sensor_polling_loop — NEVER a sleep,
# so it never blocks polling of the other servers (PERF-01 head-of-line-blocking fix).
_next_retry: dict[str, float] = {}
_COOLDOWN_SECONDS = 60.0  # non-blocking cooldown for a failing server

# Wake signal — callers (e.g. fanpilot routes that just changed fan state) can call
# wake_loop() to make the sensor loop run its next poll immediately instead of waiting
# up to poll_interval seconds. Initialized lazily inside the loop's event loop.
_wake_event: asyncio.Event | None = None


def wake_loop() -> None:
    """Signal the sensor loop to start its next poll immediately."""
    if _wake_event is not None:
        _wake_event.set()


async def _poll_one_server(server: dict, key) -> None:
    """Poll a single server's sensors with isolated error handling (PERF-01).

    Runs as one coroutine per server under asyncio.gather so one server's timeout or error
    never blocks or delays polling of the others. On failure the server is marked offline and
    placed on a NON-BLOCKING cooldown (no sleep); on success any cooldown is cleared.
    """
    from backend.core.crypto import decrypt
    from backend.modules import get_ctx

    ctx = get_ctx()  # Fresh lookup — live ctx (Decision J)
    server_id = server["id"]

    try:
        host = server["host"]
        user = decrypt(server["username_enc"], key)
        pwd = decrypt(server["password_enc"], key)

        # Read sensors
        readings = await ctx.ipmi.get_sensor_readings(host, user, pwd)
        now = datetime.now(timezone.utc).isoformat()

        # Store in database
        rows = [
            (server_id, r["name"], r["type"], r["value"], r["unit"], r["status"])
            for r in readings
            if r["value"] is not None
        ]
        if rows:
            await ctx.db.executemany(
                "INSERT INTO sensor_readings (server_id, sensor_name, sensor_type, value, unit, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
            await ctx.db.commit()

        # Update server online status
        await ctx.db.execute(
            "UPDATE servers SET is_online = 1, last_seen = CURRENT_TIMESTAMP WHERE id = ?",
            (server_id,),
        )
        await ctx.db.commit()

        # Broadcast via WebSocket. Include the unit-derived `type` so the frontend can
        # drive widgets/charts by type + real name (vendor-agnostic) instead of hardcoded
        # demo names. Names are already disambiguated by the parser, so duplicates (e.g. two
        # CPU "Temp" sensors) survive as distinct keys here.
        sensors_dict = {
            r["name"]: {
                "value": r["value"],
                "unit": r["unit"],
                "status": r["status"],
                "type": r["type"],
            }
            for r in readings
        }
        await ctx.ws.broadcast_sensor_update(server_id, sensors_dict, now)

        # 04-W6-01: EventBus removed. The former `sensor_reading` emit had no
        # subscriber and was pure indirection — the readings are already broadcast
        # by broadcast_sensor_update above and persisted to sensor_readings. The
        # former `temperature_critical` emit is now a DIRECT broadcast_alert call
        # (same try block — no asyncio.create_task indirection, log-correlated).
        for r in readings:
            if r["type"] == "temperature" and r["value"] is not None and r["value"] >= 80:
                await ctx.ws.broadcast_alert(
                    server_id=server_id,
                    severity="critical",
                    sensor=r["name"],
                    message=f"{r['name']} at {r['value']}{r.get('unit') or ''} (>= 80)",
                    value=float(r["value"]),
                )

        # Success — clear any cooldown so a recovered server resumes polling immediately.
        _next_retry.pop(server_id, None)

    except TimeoutError:
        logger.warning("Sensor poll timeout for server %s", server_id)
        await ctx.db.execute(
            "UPDATE servers SET is_online = 0 WHERE id = ?", (server_id,)
        )
        await ctx.db.commit()
        # Non-blocking cooldown — skip this server on subsequent cycles until it expires.
        _next_retry[server_id] = time.monotonic() + _COOLDOWN_SECONDS
    except Exception:
        logger.exception("Error polling server %s", server_id)
        await ctx.db.execute(
            "UPDATE servers SET is_online = 0 WHERE id = ?", (server_id,)
        )
        await ctx.db.commit()
        # Non-blocking cooldown — skip this server on subsequent cycles until it expires.
        _next_retry[server_id] = time.monotonic() + _COOLDOWN_SECONDS


async def sensor_polling_loop():
    """Main polling loop — runs until cancelled."""
    from backend.modules import get_ctx

    global _running, _wake_event
    _running = True
    # Init the wake signal inside this loop's event loop. A wake_loop() call before
    # this point is a no-op (best-effort, not load-bearing).
    _wake_event = asyncio.Event()
    logger.info("Sensor polling loop started")

    while _running:
        try:
            ctx = get_ctx()  # Look up fresh inside the loop body (Decision J)
            servers = await ctx.db.fetchall(
                "SELECT id, host, username_enc, password_enc, poll_interval FROM servers"
            )

            # Non-blocking cooldown filter — skip servers still on cooldown (LOW #11). No sleep.
            now_mono = time.monotonic()
            due = [s for s in servers if _next_retry.get(s["id"], 0.0) <= now_mono]

            # Load the encryption key ONCE per cycle and reuse across all due servers.
            key = None
            if due:
                from backend.main import auth
                key = auth.get_encryption_key()

            # Poll all due servers concurrently — one server's timeout/error never blocks the
            # others (PERF-01). return_exceptions=True so a failing coroutine never cancels the
            # gather (per-server try/except already isolates failures in _poll_one_server).
            await asyncio.gather(
                *(_poll_one_server(s, key) for s in due),
                return_exceptions=True,
            )

        except asyncio.CancelledError:
            logger.info("Sensor polling loop cancelled")
            _running = False
            _wake_event = None
            return
        except Exception:
            logger.exception("Error in sensor polling loop")

        # Sleep until the next interval OR until a user action calls wake_loop()
        # (e.g. fanpilot set_mode). The wake_for/timeout pattern matches fanpilot.
        # Re-fetch ctx so the timeout is valid even if the try block above raised
        # before binding ctx (Decision J — fresh lookup, never a stale binding).
        poll_interval = get_ctx().config.ipmi.poll_interval
        try:
            await asyncio.wait_for(_wake_event.wait(), timeout=poll_interval)
        except asyncio.TimeoutError:
            pass
        _wake_event.clear()


async def _resolved_retention_days(db, config) -> int:
    """Effective retention window — app_config override first, config default fallback.

    04-W5-01 (Plan 04-08): the Data Settings card persists `data.retention_days` to
    app_config (RESEARCH Pitfall 8 — avoids YAML comment stomping), so an OFF→ON change
    takes effect at the next cleanup pass without a restart or YAML rewrite.
    """
    override = await db.get_config("data.retention_days", default=None)
    if override:
        try:
            return int(override)
        except ValueError:
            pass
    return int(config.data.retention_days)


async def retention_cleanup_once(db, config) -> int:
    """Single retention cleanup pass. Returns the number of rows deleted.

    Extracted so POST /api/system/retention-cleanup-now can trigger an immediate pass
    (04-W5-01) and the daily loop can reuse the exact same logic. Reads the retention
    window from app_config first (see _resolved_retention_days).
    """
    days = await _resolved_retention_days(db, config)
    cursor = await db.execute(
        "DELETE FROM sensor_readings WHERE timestamp < datetime('now', ?)",
        (f"-{days} days",),
    )
    deleted = cursor.rowcount if cursor.rowcount is not None and cursor.rowcount >= 0 else 0
    await db.commit()
    return deleted


async def retention_cleanup_loop():
    """Daily cleanup of old sensor data beyond retention period."""
    from backend.modules import get_ctx

    while True:
        try:
            await asyncio.sleep(3600)  # Check every hour
            ctx = get_ctx()  # Look up fresh inside the loop body (Decision J)
            deleted = await retention_cleanup_once(ctx.db, ctx.config)
            logger.info("Retention cleanup: removed %d old sensor reading(s)", deleted)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Error in retention cleanup")
