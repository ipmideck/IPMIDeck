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

    # === FIX-03 layer 3: Startup recovery ===
    # If the previous run was killed uncleanly (kill -9, power loss, OOM kill),
    # the lifespan shutdown hook may not have fired and fans could still be in
    # manual mode on some BMCs. Detect this by reading command_log: any server
    # whose latest fan_mode entry is 'manual' or 'fanpilot' (and not followed
    # by 'auto') needs restoration BEFORE we start the main loop.
    # Reads ONLY core schema (command_log, servers) — never module-specific tables.
    try:
        recovery_rows = await ctx.db.fetchall(
            """
            SELECT cl.server_id, cl.command_detail
            FROM command_log cl
            INNER JOIN (
                SELECT server_id, MAX(timestamp) as max_ts
                FROM command_log
                WHERE command_type = 'fan_mode'
                GROUP BY server_id
            ) latest ON cl.server_id = latest.server_id AND cl.timestamp = latest.max_ts
            WHERE cl.command_type = 'fan_mode'
              AND cl.command_detail IN ('manual', 'fanpilot')
            """
        )
        if recovery_rows:
            logger.warning(
                "FanPilot startup recovery: %d server(s) had unclean shutdown",
                len(recovery_rows),
            )
            key = auth.get_encryption_key()
            for row in recovery_rows:
                server_id = row["server_id"]
                prev_mode = row["command_detail"]
                try:
                    server = await ctx.db.fetchone(
                        "SELECT host, username_enc, password_enc FROM servers WHERE id = ?",
                        (server_id,),
                    )
                    if not server:
                        logger.warning(
                            "Recovery: server %s not found, skipping", server_id,
                        )
                        continue
                    host = server["host"]
                    user = decrypt(server["username_enc"], key)
                    pwd = decrypt(server["password_enc"], key)
                    await ctx.ipmi.set_fan_mode(host, user, pwd, manual=False)
                    # Log the recovery so the next startup does not re-trigger.
                    await ctx.db.execute(
                        "INSERT INTO command_log (server_id, command_type, command_detail, result) "
                        "VALUES (?, ?, ?, ?)",
                        (server_id, "fan_mode", "auto", "recovered"),
                    )
                    await ctx.db.commit()
                    logger.warning(
                        "Recovered fan mode for server %s (was '%s')",
                        server_id, prev_mode,
                    )
                except Exception:
                    # Per-server isolation: one bad BMC must not block recovery for others.
                    logger.exception("Failed recovery for server %s", server_id)
        else:
            logger.info("FanPilot startup recovery: no servers need restoration")
    except Exception:
        # Recovery is best-effort; if the query itself fails (e.g., DB issue),
        # log and continue into the main loop. The main loop's per-iteration
        # error handling will then take over.
        logger.exception("FanPilot startup recovery query failed; continuing")

    # === End FIX-03 layer 3 ===

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

        await asyncio.sleep(30)


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
