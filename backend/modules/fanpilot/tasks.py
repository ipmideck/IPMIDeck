"""FanPilot background task — applies fan curves based on sensor readings."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from backend.core.ipmi_service import is_fan_capable
from backend.modules.fanpilot.engine import FanPilotController

logger = logging.getLogger("ipmideck.modules.fanpilot")

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

# 08-03 (D-14): one-shot skip alert for MONITORING-ONLY vendors (hpe/lenovo/generic —
# is_fan_capable(vendor) is False). Maps str server_id -> the vendor last alerted, so the loop
# alerts ONCE per (server, vendor) instead of every tick. Because the loop NEVER mutates
# fanpilot_enabled for these servers (unlike the write_rejected fail-safe), switching the
# server's vendor to a fan-capable one auto-resumes control on a later tick; the else-branch
# pops the entry so a later monitoring-only switch re-arms the alert. Cleared on
# fanpilot_shutdown() alongside the other per-server maps.
_monitoring_only_alerted: dict[str, str] = {}

# === P0-2 (FANPILOT-FAILSAFE-VALUE): garbage-value plausibility guard ===
# A *fresh* sensor row holding an implausible value falls through the Phase-4
# freshness gate (timestamp-only, value-blind), so the curve would happily cool
# to idle on a 0 C reading (interpolate_curve floors to the lowest curve point at
# temp <= points[0]). This value-domain guard rejects implausible temps; a SINGLE
# transient bad read must NOT trip — only N consecutive bad ticks route through the
# existing fail-safe primitive (CONTEXT D-P02-01..04). Bounds/N are named constants
# so they are easy to tune (Claude's discretion per CONTEXT).
GARBAGE_TEMP_FLOOR_C = 0.0      # <= floor is garbage (disabled-sensor-reports-0 case)
GARBAGE_TEMP_CEILING_C = 150.0  # >= ceiling is garbage (runaway/garbage-high)
GARBAGE_DEBOUNCE_TICKS = 3      # consecutive bad ticks before fail-safe (CONTEXT D-P02-02)
# Per-server consecutive-bad-tick counter (str server_id keys — mirrors
# _last_online_state / _controllers). Cleared on fanpilot_shutdown().
_garbage_counts: dict[str, int] = {}


def _check_garbage_value(server_id: str, value: float) -> bool:
    """Update the per-server debounce counter for one tick; return True to trip fail-safe.

    A value at/below GARBAGE_TEMP_FLOOR_C or at/above GARBAGE_TEMP_CEILING_C is a "bad
    tick": the counter increments and we return True only once it reaches
    GARBAGE_DEBOUNCE_TICKS (so a single transient bad read never trips). A plausible
    value resets the counter to 0 and returns False. The fan loop calls this helper
    inline so behavior is identical to a direct guard; factored out only so the debounce
    logic is unit-testable without driving the whole loop.
    """
    if value <= GARBAGE_TEMP_FLOOR_C or value >= GARBAGE_TEMP_CEILING_C:
        _garbage_counts[server_id] = _garbage_counts.get(server_id, 0) + 1
        return _garbage_counts[server_id] >= GARBAGE_DEBOUNCE_TICKS
    # Good read — reset the per-server counter so transient blips don't accumulate.
    _garbage_counts[server_id] = 0
    return False


# === C11 (FANPILOT-FAILSAFE-VALUE): vanished source sensor gap guard ===
# A vanished source row (missing / NULL value) is INVISIBLE to the downstream Phase-4
# freshness gate (which only runs when a row exists), so a disappearing source sensor would
# otherwise leave the fans pinned indefinitely with the controller blind. Track the gap here
# per server: seeded to 'now' on first sight so a SINGLE missing tick never trips; only a
# sustained gap (>= stale_threshold) routes through the SAME fail-safe primitive. Monotonic
# seconds (jump-free). Cleared in _recover_to_bmc_auto + fanpilot_shutdown.
_source_last_seen: dict[str, float] = {}


def _check_source_missing(
    server_id: str, has_reading: bool, stale_threshold: float, now: float | None = None
) -> bool:
    """Update the per-server source-gap tracker for one tick; return True to trip fail-safe.

    Mirrors _check_garbage_value (monotonic clock injectable for tests). A usable reading
    refreshes last-seen and returns False. A missing reading on FIRST sight seeds last-seen
    to now and returns False (a single missing tick never trips). A missing reading whose
    recorded last-seen is older than stale_threshold returns True.
    """
    import time

    t = now if now is not None else time.monotonic()
    if has_reading:
        _source_last_seen[server_id] = t
        return False
    last = _source_last_seen.get(server_id)
    if last is None:
        # First sight: seed, don't trip on one missing tick.
        _source_last_seen[server_id] = t
        return False
    return (t - last) >= stale_threshold


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


def _resolve_failsafe(mode_raw: str | None, speed_raw: str | None) -> tuple[str, int]:
    """Normalize the persisted fail-safe config into (mode, speed).

    quick-260626-4px: defaults are safety-first — mode='fixed', speed=100 — so a
    missing/garbage config "fails to full fan speed" (BMC auto under-cools
    third-party GPUs the BMC's own fan curve does not model). speed is clamped to
    0..100; any parse error falls back to 100.
    """
    mode = (mode_raw or "fixed").lower()
    if mode not in ("fixed", "bmc_auto"):
        mode = "fixed"
    try:
        speed = int(speed_raw if speed_raw not in (None, "") else 100)
    except (TypeError, ValueError):
        speed = 100
    speed = max(0, min(100, speed))
    return mode, speed


async def _recover_to_bmc_auto(
    ctx,
    server_id: str,
    host: str,
    username_enc: str,
    password_enc: str,
    reason: str,
    vendor: str = "dell",
) -> None:
    """Best-effort apply the fail-safe action + persist fanpilot_enabled=0 + log to command_log.

    Implements both 04-W1-01 (offline transition) and 04-W1-02 (stale sensor)
    recovery pathways. The applied action is governed by the operator's fail-safe
    setting (quick-260626-4px), read from app_config defaulting safety-first:

      - fanpilot.failsafe_mode == "fixed" (DEFAULT): force manual mode at
        fanpilot.failsafe_speed (default 100). "Fail to full speed" — BMC auto
        under-cools third-party GPUs the BMC does not model in its fan curve.
      - fanpilot.failsafe_mode == "bmc_auto": restore BMC-auto (legacy behavior).

    The command_log INSERT uses the REAL schema columns (command_type,
    command_detail, result — Decision F).

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
        vendor: Server vendor for 04-W4-02 dispatch. Defaults to 'dell' so an
            unconfigured row keeps the Dell baseline.
    """
    from backend.core.crypto import decrypt
    from backend.main import auth

    # quick-260626-4px: read the operator's fail-safe choice (defaults safety-first
    # when the row is missing — fixed @ 100). Mode flips take effect at the next
    # recovery without restart.
    mode, speed = _resolve_failsafe(
        await ctx.db.get_config("fanpilot.failsafe_mode", "fixed"),
        await ctx.db.get_config("fanpilot.failsafe_speed", "100"),
    )
    vendor = vendor or "dell"

    # Best-effort IPMI apply. Decryption can raise if the credential blob is
    # malformed; wrap it. 04-W4-02: forward the server vendor (Decision G default).
    #
    # PITFALL 5 (D-P03-05): after 05-01, set_fan_* RETURN a FanWriteResult instead of
    # raising on a BMC rejection. A HARD-rejected fail-safe write (the doubly-rejected
    # 0xd4 case — the BMC won't even accept the fail-safe command) returns ok=False
    # WITHOUT raising, so the bare try/except no longer catches it. We must inspect the
    # returned .ok here: if the fail-safe write itself was rejected, the fail-safe did
    # NOT apply — record alert-only, never claim 'applied'. `ipmi_ok` distinguishes a
    # genuinely-applied fail-safe from one the BMC refused. `failsafe_rejected` is set
    # only when a write returned not-ok (vs an exception, which is the offline case).
    ipmi_ok = True
    failsafe_rejected = False
    try:
        key = auth.get_encryption_key()
        user = decrypt(username_enc, key)
        pwd = decrypt(password_enc, key)
        if mode == "fixed":
            # Force manual mode and pin the configured speed (fail to full speed).
            mode_r = await asyncio.wait_for(
                ctx.ipmi.set_fan_mode(host, user, pwd, manual=True, vendor=vendor),
                timeout=5.0,
            )
            speed_r = await asyncio.wait_for(
                ctx.ipmi.set_fan_speed(host, user, pwd, speed, vendor=vendor),
                timeout=5.0,
            )
            # The fail-safe applied only if BOTH the mode and speed writes were accepted.
            if (mode_r is not None and not mode_r.ok) or (
                speed_r is not None and not speed_r.ok
            ):
                ipmi_ok = False
                failsafe_rejected = True
        else:  # bmc_auto — restore BMC-auto fan mode (legacy behavior).
            mode_r = await asyncio.wait_for(
                ctx.ipmi.set_fan_mode(host, user, pwd, manual=False, vendor=vendor),
                timeout=5.0,
            )
            if mode_r is not None and not mode_r.ok:
                ipmi_ok = False
                failsafe_rejected = True
        if failsafe_rejected:
            # The BMC accepted the connection but REJECTED the fail-safe command itself
            # (e.g. 0xd4 lockout). The loop's write_rejected path already broadcasts a
            # critical alert AFTER this call, so the operator is signalled; our job here
            # is to NOT record a false "applied".
            logger.warning(
                "FanPilot fail-safe write also rejected; alert-only server_id=%s reason=%s",
                server_id, reason,
            )
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
    # doesn't auto-resume manual mode (CONTEXT 04-W1-01: stay recovered, user
    # must manually re-engage).
    try:
        # (unchanged) always persist the enabled=0 idempotency anchor — every reason, every
        # ipmi state (incl. the unreachable-BMC exception path) — so the next online tick
        # doesn't auto-resume manual mode.
        await ctx.db.execute(
            "UPDATE servers SET fanpilot_enabled = 0 WHERE id = ?",
            (server_id,),
        )
        # C13: a recovered FANPILOT-intent server must not be re-marked 'fanpilot' by
        # _startup_state_resume (status/reality drift — the loop never drives a recovered
        # server). Realign ONLY the 'fanpilot' row, and ONLY when the fail-safe genuinely
        # applied (ipmi_ok and not failsafe_rejected). A deliberate 'manual' pin is
        # intentionally LEFT UNTOUCHED so it survives recovery + restart (C8 / D-SR / the
        # GPU-cook invariant) — that is why the UPDATE is scoped to fan_desired_mode='fanpilot'
        # and never an unconditional intent clear. command_log.result encodes the applied
        # fail-safe; fan_desired_* is the durable resume intent only.
        if ipmi_ok and not failsafe_rejected:
            await ctx.db.execute(
                "UPDATE servers SET fan_desired_mode = 'auto', fan_desired_speed = NULL "
                "WHERE id = ? AND fan_desired_mode = 'fanpilot'",
                (server_id,),
            )
        # FIX-03 idempotency (quick-260626-4px option (a)): command_detail STAYS
        # 'auto' for BOTH branches so the FIX-03 layer-3 startup-recovery query
        # (which only re-fires when the latest fan_mode command_detail is 'manual'
        # or 'fanpilot') is left untouched and never loops. The APPLIED action is
        # encoded in `result` instead: 'failsafe_fixed_<speed>' vs 'failsafe_auto'.
        #
        # PITFALL 5: when the fail-safe write ITSELF was rejected by the BMC
        # (failsafe_rejected), do NOT record an "applied" marker — the fail-safe did
        # not take effect. Record 'failsafe_rejected' so the audit trail is honest;
        # the loop already raised a critical alert for the operator. (A plain offline
        # BMC — exception path, ipmi_ok False but NOT failsafe_rejected — keeps the
        # existing applied marker: that case is the EXPECTED unreachable-BMC flow where
        # persisting fanpilot_enabled=0 prevents an auto-resume loop next tick.)
        if failsafe_rejected:
            result = "failsafe_rejected"
        else:
            result = f"failsafe_fixed_{speed}" if mode == "fixed" else "failsafe_auto"
        await ctx.db.execute(
            "INSERT INTO command_log (server_id, command_type, command_detail, result) "
            "VALUES (?, ?, ?, ?)",
            (server_id, "fan_mode", "auto", result),
        )
        await ctx.db.commit()
    except Exception:
        logger.exception("FanPilot recovery: DB persist failed for server %s", server_id)
        return

    # Reflect what was ACTUALLY applied in the in-memory mode cache so /status is
    # accurate immediately. fixed -> manual @ speed; bmc_auto -> auto.
    if mode == "fixed":
        set_last_state(server_id, "manual", speed)
    else:
        set_last_state(server_id, "auto")
    # Drop the controller; user must re-engage to recreate it with the new
    # profile settings (CONTEXT 04-W1-01: no auto-resume after recovery).
    _controllers.pop(server_id, None)
    # C11: clear the source-gap tracker so a recovered server starts fresh on re-engage.
    _source_last_seen.pop(server_id, None)

    logger.warning(
        "FanPilot fail-safe applied server_id=%s reason=%s mode=%s speed=%s ipmi=%s",
        server_id, reason, mode, speed if mode == "fixed" else "-",
        "ok" if ipmi_ok else "skipped_bmc_unreachable",
    )


# === P0-3 read-back state ===
# Per-server pending read-back record set by an ACCEPTED write and consumed on the NEXT
# tick (D-P03-02: prefer next-tick directional compare — no latency in the write path).
# Shape: {"target": int, "baseline_rpm": float | None}. baseline_rpm is the mean fan RPM
# captured at command time so the next tick can check DIRECTIONAL movement. Cleared in
# fanpilot_shutdown(). Read-back is best-effort and NEVER trips recovery.
_pending_readback: dict[str, dict] = {}
# C12: per-server last-COMMANDED speed (survives across ticks, unlike _pending_readback which
# is popped each tick by _readback_confirm). Gives the read-back a REAL directional baseline so
# a down-command whose RPM drifts up is not mislabeled 'confirmed'. Observability only — NO
# thermal-safety change (read-back still never trips recovery). Cleared in fanpilot_shutdown().
_last_commanded_speed: dict[str, int] = {}
# Read-back dead-band: ignore RPM changes smaller than this fraction of baseline OR this
# many absolute RPM (sensor jitter is not movement). 05-RESEARCH §"P0-3 RPM Read-Back".
_READBACK_DEADBAND_FRAC = 0.05
_READBACK_DEADBAND_RPM = 200.0
# Bounded in-tick retries for a TRANSIENT fan write (~1-2s backoff each — D-P03-04).
_WRITE_RETRY_ATTEMPTS = 3


def _mean_fan_rpm(readings: list[dict]) -> float | None:
    """Mean RPM of fan-type sensors with a numeric value, or None if none readable.

    Selects fans by type=="fan" (unit-derived) — NEVER by name regex (Supermicro fan
    names have no "RPM"; 05-RESEARCH §"Fan RPM sensor naming").
    """
    rpms = [
        float(r["value"])
        for r in readings
        if r.get("type") == "fan" and isinstance(r.get("value"), (int, float))
    ]
    if not rpms:
        return None
    return sum(rpms) / len(rpms)


async def _record_command_log(ctx, server_id: str, detail: str, result: str) -> None:
    """Best-effort command_log INSERT (the loop's own outcome marker)."""
    try:
        await ctx.db.execute(
            "INSERT INTO command_log (server_id, command_type, command_detail, result) "
            "VALUES (?, ?, ?, ?)",
            (server_id, "fan_mode", detail, result),
        )
        await ctx.db.commit()
    except Exception:
        logger.exception("FanPilot: command_log write failed for server %s", server_id)


async def _readback_confirm(ctx, server) -> None:
    """Best-effort RPM read-back of a PRIOR accepted write — observational, never a trip.

    Runs at the TOP of a tick for any server with a pending read-back from the previous
    tick. Reads fan RPM (type=="fan"), compares DIRECTIONALLY vs the captured baseline with
    a dead-band, and records command_log result='confirmed' (moved the right way) or
    'applied_unverified' (no readable RPM / inconclusive / read error). NEVER calls
    _recover_to_bmc_auto — read-back is the confirming layer, not a fail-safe trigger
    (D-P03-02 / Success Criterion #3).
    """
    server_id = server["id"]
    pending = _pending_readback.pop(server_id, None)
    if pending is None:
        return
    from backend.core.crypto import decrypt
    from backend.main import auth

    result = "applied_unverified"
    try:
        key = auth.get_encryption_key()
        user = decrypt(server["username_enc"], key)
        pwd = decrypt(server["password_enc"], key)
        readings = await ctx.ipmi.get_sensor_readings(server["host"], user, pwd)
        now_rpm = _mean_fan_rpm(readings)
        baseline = pending.get("baseline_rpm")
        prev_target = pending.get("prev_target", pending["target"])
        # C12: skip the directional 'confirmed' when the target is UNCHANGED — no thermal
        # change occurred, so direction is undefined and an RPM move (either way) must not be
        # claimed as a directional confirmation. Leaves 'applied_unverified'.
        if now_rpm is not None and baseline is not None and pending["target"] != prev_target:
            delta = now_rpm - baseline
            dead_band = max(_READBACK_DEADBAND_RPM, baseline * _READBACK_DEADBAND_FRAC)
            commanded_up = pending["target"] > prev_target
            if abs(delta) >= dead_band and (
                (commanded_up and delta > 0) or (not commanded_up and delta < 0)
            ):
                result = "confirmed"
    except Exception:
        # Read-back is best-effort; a read error is inconclusive, NOT a trip.
        logger.debug("FanPilot read-back inconclusive for server %s", server_id, exc_info=True)
    await _record_command_log(ctx, server_id, "fanpilot", result)


async def _apply_fan_write(ctx, server, target_speed: int) -> bool:
    """Apply a FanPilot fan write and react to the FanWriteResult (P0-3 / D-P03-04).

    Returns True when the write was ACCEPTED and the caller may broadcast active control;
    False when it fell back to fail-safe (the caller must NOT broadcast a false 'active').

    Reaction policy:
      - transient failure -> up to _WRITE_RETRY_ATTEMPTS in-tick retries (~1-2s backoff)
      - hard reject / unsupported -> NO retries (deterministic; retrying can't succeed)
      - either exhaustion -> _recover_to_bmc_auto(reason='write_rejected') + critical alert
      - accepted -> arm a best-effort next-tick read-back (records applied_unverified)
    """
    from backend.core.crypto import decrypt
    from backend.main import auth

    server_id = server["id"]
    host = server["host"]
    vendor = server["vendor"] or "dell"
    key = auth.get_encryption_key()
    user = decrypt(server["username_enc"], key)
    pwd = decrypt(server["password_enc"], key)

    # Capture a baseline mean fan RPM BEFORE the write so the next-tick read-back can
    # check directional movement. Best-effort — a read error just means no baseline.
    baseline_rpm: float | None = None
    try:
        baseline_rpm = _mean_fan_rpm(
            await ctx.ipmi.get_sensor_readings(host, user, pwd)
        )
    except Exception:
        baseline_rpm = None

    mode_res = await ctx.ipmi.set_fan_mode(host, user, pwd, manual=True, vendor=vendor)
    res = await ctx.ipmi.set_fan_speed(host, user, pwd, target_speed, vendor=vendor)
    # A rejected mode set is as fatal as a rejected speed set.
    if mode_res is not None and not mode_res.ok:
        res = mode_res

    if not res.ok:
        if res.kind == "transient":
            # Bounded in-tick retries only for transient failures (D-P03-04). A hard
            # reject / unsupported skips this loop entirely — retrying can't succeed.
            # C2: retry BOTH writes; a transient mode failure must not be masked by a
            # successful speed retry (the BMC could otherwise stay in auto while the speed
            # write reports ok). Mirror the initial-attempt fold and break only when BOTH ok.
            for attempt in range(_WRITE_RETRY_ATTEMPTS):
                await asyncio.sleep(1.0 * (attempt + 1))
                mode_res = await ctx.ipmi.set_fan_mode(host, user, pwd, manual=True, vendor=vendor)
                res = await ctx.ipmi.set_fan_speed(host, user, pwd, target_speed, vendor=vendor)
                # A rejected mode set is as fatal as a rejected speed set (same fold as above).
                if mode_res is not None and not mode_res.ok:
                    res = mode_res
                if res.ok:
                    break
        if not res.ok:
            # Hard reject OR retries exhausted OR unsupported -> fail-safe + alert + STOP
            # broadcasting active control (today the loop swallowed the exception and still
            # broadcast a false 'fanpilot active').
            await _recover_to_bmc_auto(
                ctx, server_id, server["host"], server["username_enc"],
                server["password_enc"], reason="write_rejected",
                vendor=server["vendor"] or "dell",
            )
            await ctx.ws.broadcast_alert(
                server_id, "critical", "FanPilot",
                f"Fan write rejected ({res.detail})", target_speed,
            )
            return False  # caller must NOT broadcast a false 'fanpilot active'

    # Accepted: arm a best-effort next-tick read-back. Never blocks the write path.
    # C12: use the REAL last-commanded speed as prev_target (the prior pending record is
    # popped each tick by _readback_confirm, so reading it here would always equal target and
    # make commanded_up always True). Default to target_speed on first command (direction
    # undefined -> the read-back skips the directional 'confirmed' for an unchanged target).
    prev_commanded = _last_commanded_speed.get(server_id, target_speed)
    _pending_readback[server_id] = {
        "target": target_speed,
        "prev_target": prev_commanded,
        "baseline_rpm": baseline_rpm,
    }
    # Record this as the last-commanded speed so the NEXT command's read-back has a real
    # directional baseline (set AFTER arming so prev_target above is the prior command).
    _last_commanded_speed[server_id] = target_speed
    return True


async def _startup_state_resume(ctx) -> None:
    """SR: explicit-state startup resume (replaces the FIX-03 layer-3 command_log inference).

    Runs ONCE before the main loop. Computes the downtime gap from the global heartbeat
    (fanpilot.last_alive_at, naive UTC) and, for every server carrying a non-auto DESIRED
    intent, either RESUMES that intent (short gap) or applies the operator FAIL-SAFE (long
    gap) — NEVER a silent BMC auto, NEVER an auto-revert of a deliberate manual pin.

    Decision matrix (D-SR-02..05):
      * no heartbeat (first boot / fresh DB) -> gap is None -> NO-OP for every server
        (nothing to resume; do NOT reset or fail-safe — there was no prior run to recover from).
      * gap < fanpilot.resume_threshold_seconds (default 3600) -> RESUME persisted intent:
          - manual @ fan_desired_speed -> re-issue set_fan_mode(manual=True)+set_fan_speed via
            the 05-01 structured-write path; honor .ok (a rejected resume is logged, never a
            claimed success); reflect manual @ speed in the in-memory cache.
          - fanpilot -> leave fanpilot_enabled=1; the main loop drives it. Reflect 'fanpilot'.
      * gap >= threshold (stale) -> _recover_to_bmc_auto(reason="startup_stale") — the operator
        fail-safe (default fixed @ 100), NEVER a silent BMC auto.

    Idempotency: because the decision reads EXPLICIT columns + the heartbeat (not command_log),
    a manual server with gap < threshold STAYS manual across repeated restarts — intended, not a
    loop. No 'recovered' command_log marker is needed for startup logic anymore (that marker only
    existed to stop the old command_log query from re-firing).
    """
    from backend.core.crypto import decrypt
    from backend.main import auth

    try:
        last_alive_raw = await ctx.db.get_config("fanpilot.last_alive_at", None)
        threshold = int(
            await ctx.db.get_config("fanpilot.resume_threshold_seconds", "3600") or "3600"
        )
        last_alive = _parse_sqlite_timestamp(last_alive_raw)
        # NAIVE UTC on both sides (FanPilot module convention) — mixing naive/aware raises.
        gap = (datetime.utcnow() - last_alive).total_seconds() if last_alive else None

        # Servers with a non-auto desired intent (or a still-enabled fanpilot) need a
        # resume/fail-safe decision. fan_desired_mode is the 05-03 durable intent column.
        intent_rows = await ctx.db.fetchall(
            "SELECT id, host, username_enc, password_enc, vendor, "
            "fan_desired_mode, fan_desired_speed, fanpilot_enabled "
            "FROM servers "
            "WHERE fan_desired_mode IN ('manual', 'fanpilot') OR fanpilot_enabled = 1"
        )
        if not intent_rows:
            logger.info("FanPilot startup resume: no servers with non-auto intent")
            return
        if gap is None:
            # First boot / no heartbeat — nothing to resume; do NOT reset or fail-safe.
            logger.info(
                "FanPilot startup resume: no heartbeat (first boot); leaving "
                "%d server(s) as-is", len(intent_rows),
            )
            return

        key = auth.get_encryption_key()
        for row in intent_rows:
            server_id = row["id"]
            desired_mode = row["fan_desired_mode"] or ""
            try:
                if gap < threshold:
                    # RESUME persisted intent — a manual 100% pin survives a quick restart.
                    if desired_mode == "manual" and row["fan_desired_speed"] is not None:
                        speed = int(row["fan_desired_speed"])
                        host = row["host"]
                        user = decrypt(row["username_enc"], key)
                        pwd = decrypt(row["password_enc"], key)
                        vendor = row["vendor"] or "dell"
                        # 05-01 structured-write path; honor .ok (a rejected resume must not
                        # be claimed as success).
                        mode_r = await ctx.ipmi.set_fan_mode(
                            host, user, pwd, manual=True, vendor=vendor
                        )
                        speed_r = await ctx.ipmi.set_fan_speed(
                            host, user, pwd, speed, vendor=vendor
                        )
                        resume_ok = (mode_r is None or mode_r.ok) and (
                            speed_r is None or speed_r.ok
                        )
                        if resume_ok:
                            set_last_state(server_id, "manual", speed)
                            logger.info(
                                "FanPilot startup resume: re-applied manual @ %d%% "
                                "server_id=%s gap=%.0fs", speed, server_id, gap,
                            )
                        else:
                            # C9: a rejected resume is NOT a success — FAIL SAFE (operator
                            # failsafe) + critical alert, mirroring the runtime _apply_fan_write
                            # rejection path. Log-only would leave an unknown fan state (the
                            # GPU-cook condition on the resume path).
                            failed = (
                                speed_r if (speed_r is not None and not speed_r.ok) else mode_r
                            )
                            logger.warning(
                                "FanPilot startup resume: manual re-apply REJECTED -> fail-safe "
                                "server_id=%s detail=%s",
                                server_id,
                                failed.detail if failed is not None else "",
                            )
                            await _recover_to_bmc_auto(
                                ctx, server_id, row["host"], row["username_enc"],
                                row["password_enc"], reason="startup_resume_rejected",
                                vendor=row["vendor"] or "dell",
                            )
                            # ctx.ws may be None in some call paths — guard the alert.
                            if ctx.ws is not None:
                                await ctx.ws.broadcast_alert(
                                    server_id, "critical", "FanPilot",
                                    f"Startup resume rejected "
                                    f"({failed.detail if failed is not None else ''})",
                                    speed,
                                )
                    elif desired_mode == "fanpilot" or row["fanpilot_enabled"]:
                        # Keep fanpilot_enabled=1; the main loop drives the write. Reflect
                        # the resumed mode in the cache so /status is honest immediately.
                        set_last_state(server_id, "fanpilot")
                        logger.info(
                            "FanPilot startup resume: keeping fanpilot enabled "
                            "server_id=%s gap=%.0fs", server_id, gap,
                        )
                else:
                    # STALE: gap >= threshold -> operator fail-safe (NEVER silent BMC auto).
                    # Don't blindly re-apply a possibly-stale low value across a long outage.
                    logger.warning(
                        "FanPilot startup resume: STALE gap=%.0fs >= threshold=%ds -> "
                        "fail-safe server_id=%s", gap, threshold, server_id,
                    )
                    await _recover_to_bmc_auto(
                        ctx, server_id, row["host"], row["username_enc"],
                        row["password_enc"], reason="startup_stale",
                        vendor=row["vendor"] or "dell",
                    )
            except Exception:
                # Per-server isolation: one bad BMC must not block resume for the others.
                logger.exception(
                    "FanPilot startup resume failed for server %s", server_id
                )
    except Exception:
        # Best-effort: a query/config failure must not stop the loop from starting.
        logger.exception("FanPilot startup state-resume failed; continuing")


async def fanpilot_loop():
    """Background task that applies fan curves to all servers with FanPilot enabled."""
    from backend.modules import get_ctx

    ctx = get_ctx()  # Fresh lookup — live ctx (Decision J)

    global _running
    _running = True
    logger.info("FanPilot loop started")

    # === SR: explicit-state startup resume (replaces FIX-03 layer-3 command_log inference) ===
    # Resume the operator's DESIRED fan state when the downtime gap is short (a manual 100%
    # pin survives a 3s restart — the GPU-cook fix), apply the operator fail-safe when the gap
    # is long, and NEVER silently revert a manual pin to BMC auto. See _startup_state_resume.
    await _startup_state_resume(ctx)

    # Init the wake signal inside the loop's event loop (lazy, so wake_loop() before
    # the loop starts is a no-op).
    global _wake_event
    _wake_event = asyncio.Event()

    while _running:
        try:
            ctx = get_ctx()  # Look up fresh inside the loop body (Decision J)
            # SR heartbeat (D-SR-02): write the global last_alive_at at the TOP of each tick
            # (naive UTC, FanPilot module convention) so a tick that then crashes still recorded
            # "alive a moment ago". One global write per tick — never per-server. Best-effort:
            # a heartbeat failure must never crash the loop. fanpilot.last_alive_at is INTERNAL
            # (NOT in _ALLOWED_APP_CONFIG_KEYS — never web-settable).
            try:
                await ctx.db.set_config(
                    "fanpilot.last_alive_at", datetime.utcnow().isoformat()
                )
            except Exception:
                logger.debug("FanPilot heartbeat write failed (non-fatal)", exc_info=True)
            # 04-W1-01 (Codex HIGH fix): SELECT all fanpilot_enabled=1 servers
            # regardless of is_online so the offline-transition handler CAN see
            # newly-offline rows. The previous "AND s.is_online = 1" filter made
            # offline rows invisible — recovery could never fire.
            servers = await ctx.db.fetchall(
                "SELECT s.id, s.host, s.username_enc, s.password_enc, s.vendor, "
                "s.fanpilot_profile_id, "
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

            # Note: per-server credential decryption happens inside the helper functions
            # (_apply_fan_write / _readback_confirm / _recover_to_bmc_auto), each with its
            # own call-time auth/decrypt import — the loop body itself needs neither.

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
                            vendor=server["vendor"] or "dell",
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

                # 08-03 (D-14): monitoring-only vendor (hpe/lenovo/generic — is_fan_capable
                # is False). SKIP the fan write entirely; do NOT call _apply_fan_write and do
                # NOT mutate fanpilot_enabled (so switching the vendor to a supported one
                # auto-resumes control on a later tick). Alert ONCE per (server, vendor) — never
                # once per tick — and re-arm on vendor change. This is a DIFFERENT path from the
                # write_rejected fail-safe (which sets enabled=0); the write path below is simply
                # never reached for these vendors, so the enabled=0 mutation no longer fires for
                # a monitoring-only server. The unsupported-vendor guard INSIDE _apply_fan_write
                # stays as defense-in-depth.
                vendor = server["vendor"] or "dell"
                if not is_fan_capable(vendor):
                    if _monitoring_only_alerted.get(server_id) != vendor:
                        _monitoring_only_alerted[server_id] = vendor
                        if ctx.ws is not None:
                            await ctx.ws.broadcast_alert(
                                server_id, "warning", "FanPilot",
                                f"FanPilot skipped: '{vendor}' is monitoring-only "
                                f"(no IPMI fan control). Switch to a supported vendor to "
                                f"enable control.",
                                None,
                            )
                    # Honest /status: not actively controlling (no false 'fanpilot active').
                    set_last_state(server_id, "auto")
                    continue
                # Fan-capable vendor: re-arm the one-shot flag so a later monitoring-only
                # switch alerts again.
                _monitoring_only_alerted.pop(server_id, None)

                # P0-3 best-effort read-back: confirm the PRIOR tick's accepted write
                # actually moved the fans (records 'confirmed' / 'applied_unverified').
                # Observational only — never trips recovery (D-P03-02).
                await _readback_confirm(ctx, server)

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
                # C11: a vanished source row (missing / NULL value) is invisible to the
                # freshness gate below (which only runs when a row exists). Track the gap
                # per server; a sustained gap (>= stale_threshold) routes through the SAME
                # fail-safe primitive + a critical alert. A single missing tick does NOT trip.
                has_reading = bool(reading) and reading["value"] is not None
                if not has_reading:
                    if _check_source_missing(server_id, False, stale_threshold):
                        logger.warning(
                            "FanPilot source-missing guard TRIPPED server_id=%s "
                            "threshold=%.1fs sensor=%s",
                            server_id, stale_threshold, source_sensor,
                        )
                        if auto_recover_enabled:
                            await _recover_to_bmc_auto(
                                ctx, server_id, server["host"],
                                server["username_enc"], server["password_enc"],
                                reason="source_missing", vendor=server["vendor"] or "dell",
                            )
                            await ctx.ws.broadcast_alert(
                                server_id, "critical", source_sensor,
                                "Source sensor reading vanished; failed safe", None,
                            )
                    continue
                # Usable reading: refresh the last-seen so the gap timer resets.
                _check_source_missing(server_id, True, stale_threshold)

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
                                vendor=server["vendor"] or "dell",
                            )
                        # Don't pass stale data to compute_fan_speed.
                        continue

                current_temp = reading["value"]

                # === P0-2 garbage-value guard (D-P02-01..04) ===
                # Distinct from the freshness gate above (value-blind): a FRESH row
                # holding an implausible value (<= 0 C or >= 150 C) must NEVER reach
                # the curve (it would floor fans to idle). Debounce N=3 consecutive bad
                # ticks per server so a single transient bad read doesn't trip; on
                # crossing N route through the SAME fail-safe primitive + a critical
                # alert, then skip this tick.
                if _check_garbage_value(server_id, current_temp):
                    logger.warning(
                        "FanPilot garbage-value guard TRIPPED server_id=%s value=%s "
                        "threshold=%d sensor=%s",
                        server_id, current_temp, GARBAGE_DEBOUNCE_TICKS, source_sensor,
                    )
                    await _recover_to_bmc_auto(
                        ctx, server_id, server["host"],
                        server["username_enc"], server["password_enc"],
                        reason="sensor_garbage", vendor=server["vendor"] or "dell",
                    )
                    await ctx.ws.broadcast_alert(
                        server_id, "critical", source_sensor,
                        f"Implausible sensor value {current_temp}C; failed safe",
                        current_temp,
                    )
                    # Reset after acting; recovery set fanpilot_enabled=0 so the server
                    # won't re-enter this loop until the operator re-engages.
                    _garbage_counts[server_id] = 0
                    continue
                if current_temp <= GARBAGE_TEMP_FLOOR_C or current_temp >= GARBAGE_TEMP_CEILING_C:
                    # Bad value but below the debounce threshold — log and skip this tick
                    # WITHOUT feeding the garbage to the curve (don't idle the fans on a blip).
                    logger.warning(
                        "FanPilot garbage-value guard server_id=%s value=%s count=%d/%d "
                        "sensor=%s (below trip threshold; skipping tick)",
                        server_id, current_temp, _garbage_counts.get(server_id, 0),
                        GARBAGE_DEBOUNCE_TICKS, source_sensor,
                    )
                    continue

                target_speed = ctrl.compute_fan_speed(curve_points, current_temp)

                # Apply fan speed via IPMI. P0-3: _apply_fan_write consumes the
                # FanWriteResult (transient retries / hard-reject immediate fall-back /
                # recovery+alert) and returns whether the write was ACCEPTED. A rejected
                # write returns False after firing the fail-safe — we must NOT then
                # broadcast a false 'fanpilot active'. The classified rejection is handled
                # INSIDE _apply_fan_write, not swallowed by this try/except (which now only
                # guards genuine unexpected errors — e.g. a malformed credential blob).
                try:
                    accepted = await _apply_fan_write(ctx, server, target_speed)
                    if not accepted:
                        continue  # fail-safe fired; do NOT broadcast active

                    # Broadcast status (accepted write only).
                    await ctx.ws.broadcast_fanpilot_status(
                        server_id=server_id,
                        mode="fanpilot",
                        profile=server["profile_name"] or "Custom",
                        speed_pct=target_speed,
                        source_temp=current_temp,
                    )

                    # Cache for /status — UI reads mode + current_speed_pct from here.
                    set_last_state(server_id, "fanpilot", target_speed)

                    # 04-W6-01: EventBus removed. The former `fan_speed_changed` emit
                    # had no subscriber (the audit-log target it was meant to feed
                    # doesn't exist and is out of phase scope) — deleted. The fan-speed
                    # change is already broadcast via broadcast_fanpilot_status above.

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
    from backend.core.crypto import decrypt
    from backend.main import auth  # AuthManager not in ModuleContext — kept (Decision J)
    from backend.modules import get_ctx

    ctx = get_ctx()  # Fresh lookup — live ctx (Decision J)

    global _running
    _running = False

    logger.info("FanPilot shutdown: restoring auto mode on all servers")

    servers = await ctx.db.fetchall(
        "SELECT id, host, username_enc, password_enc, vendor "
        "FROM servers WHERE fanpilot_enabled = 1"
    )

    if not servers:
        return

    key = auth.get_encryption_key()
    for server in servers:
        try:
            host = server["host"]
            user = decrypt(server["username_enc"], key)
            pwd = decrypt(server["password_enc"], key)
            # 04-W4-02: forward vendor (default 'dell' if NULL/empty).
            await ctx.ipmi.set_fan_mode(
                host, user, pwd, manual=False, vendor=server["vendor"] or "dell"
            )
            set_last_state(server["id"], "auto")
            logger.info("Restored auto fan mode on %s (%s)", server["id"], host)
        except Exception:
            logger.exception("Failed to restore auto mode on %s", server["id"])

    _controllers.clear()
    _last_state.clear()
    _last_online_state.clear()
    _monitoring_only_alerted.clear()
    _garbage_counts.clear()
    _pending_readback.clear()
    _source_last_seen.clear()
    _last_commanded_speed.clear()
    global _wake_event
    _wake_event = None
