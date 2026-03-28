"""Sensor polling background task — reads all BMC sensors and broadcasts via WebSocket."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger("ipmilink.modules.sensors")

_running = True


async def sensor_polling_loop():
    """Main polling loop — runs until cancelled."""
    import backend.modules as ctx
    from backend.core.crypto import decrypt

    global _running
    _running = True
    logger.info("Sensor polling loop started")

    while _running:
        try:
            servers = await ctx.db.fetchall(
                "SELECT id, host, username_enc, password_enc, poll_interval FROM servers"
            )

            key = None  # lazy-load encryption key

            for server in servers:
                if not _running:
                    break

                server_id = server["id"]
                poll_interval = server["poll_interval"] or 5

                try:
                    if key is None:
                        from backend.main import auth
                        key = auth.get_encryption_key()

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

                except TimeoutError:
                    logger.warning("Sensor poll timeout for server %s", server_id)
                    await ctx.db.execute(
                        "UPDATE servers SET is_online = 0 WHERE id = ?", (server_id,)
                    )
                    await ctx.db.commit()
                except Exception:
                    logger.exception("Error polling server %s", server_id)
                    await ctx.db.execute(
                        "UPDATE servers SET is_online = 0 WHERE id = ?", (server_id,)
                    )
                    await ctx.db.commit()

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
            deleted = await ctx.db.execute(
                "DELETE FROM sensor_readings WHERE timestamp < datetime('now', ?)",
                (f"-{retention} days",),
            )
            await ctx.db.commit()
            logger.info("Retention cleanup: removed old sensor data (retention: %d days)", retention)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Error in retention cleanup")
