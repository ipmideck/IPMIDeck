"""FanPilot background task — applies fan curves based on sensor readings."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from backend.modules.fanpilot.engine import FanPilotController

logger = logging.getLogger("ipmilink.modules.fanpilot")

# Active controllers per server
_controllers: dict[str, FanPilotController] = {}
_running = True

# Last known fan-control state per server — read by /api/modules/fanpilot/<id>/status
# so the UI can highlight the active mode and show the current fan-speed %.
# In-memory only; recovery on startup repopulates it (forced to {"auto", None}),
# the loop updates it after each tick, and the mode-change route updates it on
# user input.
_last_state: dict[str, dict] = {}

# 04-W1-01: Tracks the last-seen is_online state per server so the fan loop can
# detect 1→0 transitions exactly once and trigger auto-recovery. Server IDs are
# TEXT in the schema (Decision C) — use str keys. Single uvicorn worker, so
# this in-memory map is safe (PROJECT constraint: single process). Module-level
# so it survives across loop iterations; cleared on fanpilot_shutdown().
_last_online_state: dict[str, bool] = {}


def set_last_state(server_id: str, mode: str, speed_pct: int | None = None) -> None:
    """Update the cached mode/speed for a server.

    When ``mode == "auto"`` the cached speed is cleared (the BMC owns it).
    When ``speed_pct is None`` for manual/fanpilot, the previous speed is preserved.
    """
    if mode == "auto":
        _last_state[server_id] = {"mode": "auto", "speed_pct": None}
        return
    prev = _last_state.get(server_id, {})
    _last_state[server_id] = {
        "mode": mode,
        "speed_pct": speed_pct if speed_pct is not None else prev.get("speed_pct"),
    }


def get_last_state(server_id: str) -> dict:
    """Return cached state for a server, or a safe default."""
    return _last_state.get(server_id, {"mode": "auto", "speed_pct": None})


# Wake signal — lets routes ask the loop to run a tick now instead of waiting for the
# next 30s sleep. Used after a profile is edited or (re)activated, so changes propagate
# to the fans within ~1s instead of up to 30s. None until the loop starts.
_wake_event: asyncio.Event | None = None


def wake_loop() -> None:
    """Wake the fanpilot loop to run a tick immediately. No-op before the loop starts."""
    if _wake_event is not None:
        _wake_event.set()


def _parse_sqlite_timestamp(ts: str | None) -> datetime | None:
    """Normalize a SQLite-stored timestamp to a naive UTC datetime.

    SQLite's CURRENT_TIMESTAMP yields 'YYYY-MM-DD HH:MM:SS' (space, no tz).
    Some rows may come back already-normalized to ISO ('YYYY-MM-DDTHH:MM:SS[Z]')
    if produced by other code paths. Returns None on parse failure.
    """
    if not ts:
        return None
    s = ts.replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1]
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


async def _recover_to_bmc_auto(
    ctx,
    server_id: str,
    host: str,
    username_enc: str,
    password_enc: str,
    reason: str,
) -> None:
    """Best-effort restore BMC-auto fan mode + persist fanpilot_enabled=0 + log to command_log.

    Implements both 04-W1-01 (offline transition) and 04-W1-02 (stale sensor)
    recovery pathways. Manual fan mode is NEVER touched — recovery only ever
    sets manual=False. The command_log INSERT uses the REAL schema columns
    (command_type, command_detail, result — Decision F).

    Best-effort means: every step is wrapped in try/except. If BMC is
    unreachable (the offline case is the EXPECTED case), the IPMI call will
    fail and we proceed to persist + log anyway so the next loop tick doesn't
    keep re-triggering recovery.

    Args:
        ctx: backend.modules context (has db, ipmi).
        server_id: TEXT primary key from servers.id.
        host: BMC host or IP.
        username_enc / password_enc: AES-encrypted credentials from servers table.
        reason: Free-form label for the warning log line
            ("offline_transition" or "sensor_stale").
    """
    from backend.core.crypto import decrypt
    from backend.main import auth

    # Best-effort IPMI restore. Decryption can raise if the credential blob is
    # malformed; wrap it. Decision G — Plan 01 does NOT pass vendor; Plan 06
    # introduces vendor with a default that keeps this call site valid.
    try:
        key = auth.get_encryption_key()
        user = decrypt(username_enc, key)
        pwd = decrypt(password_enc, key)
        await asyncio.wait_for(
            ctx.ipmi.set_fan_mode(host, user, pwd, manual=False),
            timeout=5.0,
        )
        ipmi_ok = True
    except Exception:
        # The offline case is the EXPECTED case here — log at warning so it's
        # visible without spamming on every retry.
        logger.warning(
            "FanPilot recovery: BMC unreachable for server %s (host=%s, reason=%s)",
            server_id, host, reason,
        )
        ipmi_ok = False

    # Persist fanpilot_enabled=0 + write the idempotency marker even if the BMC
    # was unreachable — the offline-transition case is exactly when the BMC
    # CAN'T be talked to, but we still need to ensure the next online tick
    # doesn't auto-resume manual mode (CONTEXT 04-W1-01: stay in BMC-auto, user
    # must manually re-engage).
    try:
        await ctx.db.execute(
            "UPDATE servers SET fanpilot_enabled = 0 WHERE id = ?",
            (server_id,),
        )
        # The (command_type='fan_mode', command_detail='auto', result='recovered')
        # triple is the same idempotency marker FIX-03 layer 3 startup recovery
        # checks for. Startup recovery only re-fires when latest fan_mode
        # command_detail is 'manual' or 'fanpilot' — writing 'auto' here means
        # next boot's latest is 'auto' and recovery is correctly skipped.
        await ctx.db.execute(
            "INSERT INTO command_log (server_id, command_type, command_detail, result) "
            "VALUES (?, ?, ?, ?)",
            (server_id, "fan_mode", "auto", "recovered"),
        )
        await ctx.db.commit()
    except Exception:
        logger.exception("FanPilot recovery: DB persist failed for server %s", server_id)
        return

    # Reflect in the in-memory mode cache so /status reports auto immediately.
    set_last_state(server_id, "auto")
    # Drop the controller; user must re-engage to recreate it with the new
    # profile settings (CONTEXT 04-W1-01: no auto-resume after recovery).
    _controllers.pop(server_id, None)

    logger.warning(
        "FanPilot auto-recovered server_id=%s reason=%s ipmi_restore=%s",
        server_id, reason, "ok" if ipmi_ok else "skipped_bmc_unreachable",
    )


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
                    # Reflect the recovered state in the in-memory cache so /status
                    # reports "auto" immediately after startup.
                    set_last_state(server_id, "auto")
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

    # Init the wake signal inside the loop's event loop (lazy, so wake_loop() before
    # the loop starts is a no-op).
    global _wake_event
    _wake_event = asyncio.Event()

    while _running:
        try:
            # 04-W1-01 (Codex HIGH fix): SELECT all fanpilot_enabled=1 servers
            # regardless of is_online so the offline-transition handler CAN see
            # newly-offline rows. The previous "AND s.is_online = 1" filter made
            # offline rows invisible — recovery could never fire.
            servers = await ctx.db.fetchall(
                "SELECT s.id, s.host, s.username_enc, s.password_enc, s.fanpilot_profile_id, "
                "s.fanpilot_enabled, s.is_online, fp.curve_points, fp.hysteresis, "
                "fp.safety_threshold, fp.source_sensor, fp.name as profile_name "
                "FROM servers s "
                "LEFT JOIN fan_profiles fp ON s.fanpilot_profile_id = fp.id "
                "WHERE s.fanpilot_enabled = 1"
            )

            # 04-W1-01: read the runtime toggle once per cycle (default ON when
            # row is missing — safety-first per CONTEXT). OFF→ON flips take
            # effect at the next tick without restart.
            auto_recover_raw = await ctx.db.get_config(
                "fanpilot.auto_recover_on_offline", "true"
            )
            auto_recover_enabled = (auto_recover_raw or "true").lower() == "true"

            # 04-W1-02: freshness threshold = 2 × ipmi.poll_interval (seconds).
            # Derived from existing config — no new config knob per CONTEXT.
            stale_threshold = 2.0 * float(ctx.config.ipmi.poll_interval)

            key = auth.get_encryption_key() if servers else None

            for server in servers:
                if not _running:
                    break

                server_id = server["id"]
                current_online = bool(server["is_online"])
                # First time we see a server, assume it WAS online (most common
                # case after process boot); this means the FIRST tick after a
                # boot where a server is already offline does NOT spuriously
                # treat it as a transition. The startup-recovery query (FIX-03
                # layer 3) handles the unclean-shutdown case separately.
                last_online = _last_online_state.get(server_id, True)

                # 04-W1-01: Detect online→offline transition. Fire recovery at
                # most ONCE per transition. Manual mode is NEVER touched — only
                # fanpilot_enabled=1 servers reach this code path.
                if last_online and not current_online:
                    if auto_recover_enabled:
                        await _recover_to_bmc_auto(
                            ctx, server_id, server["host"],
                            server["username_enc"], server["password_enc"],
                            reason="offline_transition",
                        )
                    else:
                        logger.warning(
                            "FanPilot offline transition for server %s but "
                            "auto-recover is disabled; fans may remain pinned "
                            "at last commanded speed.", server_id,
                        )
                    _last_online_state[server_id] = False
                    # Either path (recovery fired or toggle is off): don't try
                    # to compute fan speed for an offline server.
                    continue

                _last_online_state[server_id] = current_online

                # Skip curve compute for offline servers. (Reached when the
                # server has been continuously offline across multiple ticks.)
                if not current_online:
                    continue

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

                # Get current temperature from latest sensor reading.
                # 04-W1-02: also pull the timestamp for the freshness gate.
                source_sensor = server["source_sensor"] or "CPU Temp"
                reading = await ctx.db.fetchone(
                    "SELECT value, timestamp FROM sensor_readings "
                    "WHERE server_id = ? AND sensor_name = ? "
                    "ORDER BY timestamp DESC LIMIT 1",
                    (server_id, source_sensor),
                )
                if not reading or reading["value"] is None:
                    continue

                # 04-W1-02 freshness gate: if the latest sensor reading is
                # older than 2 × poll_interval, treat as missing → trigger the
                # SAME recovery pathway as 04-W1-01. Closes the "sensor frozen
                # with is_online=1" gap (e.g. sensor rename, DB write lag).
                reading_ts = _parse_sqlite_timestamp(reading["timestamp"])
                if reading_ts is not None:
                    age_seconds = (datetime.utcnow() - reading_ts).total_seconds()
                    if age_seconds > stale_threshold:
                        logger.warning(
                            "FanPilot freshness-gate triggered server_id=%s "
                            "age=%.1fs threshold=%.1fs sensor=%s",
                            server_id, age_seconds, stale_threshold, source_sensor,
                        )
                        if auto_recover_enabled:
                            await _recover_to_bmc_auto(
                                ctx, server_id, server["host"],
                                server["username_enc"], server["password_enc"],
                                reason="sensor_stale",
                            )
                        # Don't pass stale data to compute_fan_speed.
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

                    # Cache for /status — UI reads mode + current_speed_pct from here.
                    set_last_state(server_id, "fanpilot", target_speed)

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

        # Sleep up to 30s, but wake immediately if a route called wake_loop()
        # (e.g. after a profile edit or activation), so changes go live within ~1s.
        try:
            await asyncio.wait_for(_wake_event.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass
        _wake_event.clear()


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
            set_last_state(server["id"], "auto")
            logger.info("Restored auto fan mode on %s (%s)", server["id"], host)
        except Exception:
            logger.exception("Failed to restore auto mode on %s", server["id"])

    _controllers.clear()
    _last_state.clear()
    _last_online_state.clear()
    global _wake_event
    _wake_event = None
