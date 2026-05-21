"""Sensor polling background task — reads all BMC sensors and broadcasts via WebSocket."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger("ipmilink.modules.sensors")

_running = True

# Non-blocking per-server cooldown: server_id -> monotonic ts before which we skip polling.
# A server that times out / errors is placed on this cooldown so we do not re-hit a known-offline
# BMC on every poll cycle. This is a SKIP GATE consulted by sensor_polling_loop — NEVER a sleep,
# so it never blocks polling of the other servers (PERF-01 head-of-line-blocking fix).
_next_retry: dict[str, float] = {}
_COOLDOWN_SECONDS = 60.0  # non-blocking cooldown for a failing server


async def _poll_one_server(server: dict, key) -> None:
    """Poll a single server's sensors with isolated error handling (PERF-01).

    Runs as one coroutine per server under asyncio.gather so one server's timeout or error
    never blocks or delays polling of the others. On failure the server is marked offline and
    placed on a NON-BLOCKING cooldown (no sleep); on success any cooldown is cleared.
    """
    import backend.modules as ctx
    from backend.core.crypto import decrypt

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

        # Broadcast via WebSocket
        sensors_dict = {
            r["name"]: {"value": r["value"], "unit": r["unit"], "status": r["status"]}
            for r in readings
        }
        await ctx.ws.broadcast_sensor_update(server_id, sensors_dict, now)

        # Emit event for other modules (e.g., FanPilot)
        for r in readings:
            await ctx.events.emit("sensor_reading", {
                "server_id": server_id,
                "sensor_name": r["name"],
                "sensor_type": r["type"],
                "value": r["value"],
                "unit": r["unit"],
                "status": r["status"],
            })

            # Emit critical temperature events
            if r["type"] == "temperature" and r["value"] is not None and r["value"] >= 80:
                await ctx.events.emit("temperature_critical", {
                    "server_id": server_id,
                    "sensor_name": r["name"],
                    "value": r["value"],
                    "threshold": 80,
                })

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
    import backend.modules as ctx

    global _running
    _running = True
    logger.info("Sensor polling loop started")

    while _running:
        try:
            servers = await ctx.db.fetchall(
                "SELECT id, host, username_enc, password_enc, poll_interval FROM servers"
            )

            now_mono = time.monotonic()
            due = [s for s in servers if _next_retry.get(s["id"], 0.0) <= now_mono]

            key = None
            if due:
                from backend.main import auth
                key = auth.get_encryption_key()

            for server in due:
                if not _running:
                    break
                await _poll_one_server(server, key)

        except asyncio.CancelledError:
            logger.info("Sensor polling loop cancelled")
            _running = False
            return
        except Exception:
            logger.exception("Error in sensor polling loop")

        await asyncio.sleep(ctx.config.ipmi.poll_interval)


async def retention_cleanup_loop():
    """Daily cleanup of old sensor data beyond retention period."""
    import backend.modules as ctx

    while True:
        try:
            await asyncio.sleep(3600)  # Check every hour
            retention = ctx.config.data.retention_days
            await ctx.db.execute(
                "DELETE FROM sensor_readings WHERE timestamp < datetime('now', ?)",
                (f"-{retention} days",),
            )
            await ctx.db.commit()
            logger.info("Retention cleanup: removed old sensor data (retention: %d days)", retention)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Error in retention cleanup")
