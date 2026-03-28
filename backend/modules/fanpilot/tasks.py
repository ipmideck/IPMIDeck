"""FanPilot background task — applies fan curves based on sensor readings."""

from __future__ import annotations

import asyncio
import json
import logging

from backend.modules.fanpilot.engine import FanPilotController

logger = logging.getLogger("ipmilink.modules.fanpilot")

# Active controllers per server
_controllers: dict[str, FanPilotController] = {}
_running = True


async def fanpilot_loop():
    """Background task that applies fan curves to all servers with FanPilot enabled."""
    import backend.modules as ctx
    from backend.core.crypto import decrypt
    from backend.main import auth

    global _running
    _running = True
    logger.info("FanPilot loop started")

    while _running:
        try:
            servers = await ctx.db.fetchall(
                "SELECT s.id, s.host, s.username_enc, s.password_enc, s.fanpilot_profile_id, "
                "s.fanpilot_enabled, fp.curve_points, fp.hysteresis, fp.safety_threshold, "
                "fp.source_sensor, fp.name as profile_name "
                "FROM servers s "
                "LEFT JOIN fan_profiles fp ON s.fanpilot_profile_id = fp.id "
                "WHERE s.fanpilot_enabled = 1 AND s.is_online = 1"
            )

            key = auth.get_encryption_key() if servers else None

            for server in servers:
                if not _running:
                    break

                server_id = server["id"]
                curve_json = server["curve_points"]
                if not curve_json:
                    continue

                try:
                    curve_points = json.loads(curve_json)
                except (json.JSONDecodeError, TypeError):
                    logger.error("Invalid curve JSON for server %s", server_id)
                    continue

                # Get or create controller
                if server_id not in _controllers:
                    _controllers[server_id] = FanPilotController(
                        server_id=server_id,
                        hysteresis=server["hysteresis"] or 3.0,
                        safety_threshold=server["safety_threshold"] or 85.0,
                    )
                ctrl = _controllers[server_id]

                # Get current temperature from latest sensor reading
                source_sensor = server["source_sensor"] or "CPU Temp"
                reading = await ctx.db.fetchone(
                    "SELECT value FROM sensor_readings WHERE server_id = ? AND sensor_name = ? "
                    "ORDER BY timestamp DESC LIMIT 1",
                    (server_id, source_sensor),
                )
                if not reading or reading["value"] is None:
                    continue

                current_temp = reading["value"]
                target_speed = ctrl.compute_fan_speed(curve_points, current_temp)

                # Apply fan speed via IPMI
                try:
                    host = server["host"]
                    user = decrypt(server["username_enc"], key)
                    pwd = decrypt(server["password_enc"], key)

                    await ctx.ipmi.set_fan_mode(host, user, pwd, manual=True)
                    await ctx.ipmi.set_fan_speed(host, user, pwd, target_speed)

                    # Broadcast status
                    await ctx.ws.broadcast_fanpilot_status(
                        server_id=server_id,
                        mode="fanpilot",
                        profile=server["profile_name"] or "Custom",
                        speed_pct=target_speed,
                        source_temp=current_temp,
                    )

                    # Emit event
                    await ctx.events.emit("fan_speed_changed", {
                        "server_id": server_id,
                        "speed_pct": target_speed,
                        "profile": server["profile_name"],
                        "source_temp": current_temp,
                    })

                except Exception:
                    logger.exception("FanPilot error setting speed on %s", server_id)

        except asyncio.CancelledError:
            logger.info("FanPilot loop cancelled")
            _running = False
            return
        except Exception:
            logger.exception("Error in FanPilot loop")

        await asyncio.sleep(5)


async def fanpilot_shutdown():
    """Restore auto fan mode on all servers — CRITICAL for safety."""
    import backend.modules as ctx
    from backend.core.crypto import decrypt
    from backend.main import auth

    global _running
    _running = False

    logger.info("FanPilot shutdown: restoring auto mode on all servers")

    servers = await ctx.db.fetchall(
        "SELECT id, host, username_enc, password_enc FROM servers WHERE fanpilot_enabled = 1"
    )

    if not servers:
        return

    key = auth.get_encryption_key()
    for server in servers:
        try:
            host = server["host"]
            user = decrypt(server["username_enc"], key)
            pwd = decrypt(server["password_enc"], key)
            await ctx.ipmi.set_fan_mode(host, user, pwd, manual=False)
            logger.info("Restored auto fan mode on %s (%s)", server["id"], host)
        except Exception:
            logger.exception("Failed to restore auto mode on %s", server["id"])

    _controllers.clear()
