"""FanPilot fail-safe recovery branches (quick-260626-4px).

The recovery primitive `_recover_to_bmc_auto` in backend/modules/fanpilot/tasks.py now
honors the operator-chosen fail-safe behavior read from app_config:

  - fanpilot.failsafe_mode == "fixed"  -> set_fan_mode(manual=True) + set_fan_speed(speed)
  - fanpilot.failsafe_mode == "bmc_auto" -> set_fan_mode(manual=False)  (legacy behavior)
  - missing config                      -> defaults to fixed @ 100 (safety-first)

It MUST still, in EVERY branch: UPDATE servers SET fanpilot_enabled=0, INSERT the FIX-03
idempotency marker into command_log (command_detail stays 'auto' so startup-recovery does
NOT loop — only `result` reflects the applied action), and update the in-memory _last_state.

These tests use ONLY fakes — no real BMC, ipmitool, or DB. asyncio_mode="auto" (pyproject)
means async tests need NO decorator. We monkeypatch the call-time imports the function makes
(`backend.main.auth` and `backend.core.crypto.decrypt`) so no real encryption key/blob is needed.
The previous ctx is restored in a finally (the SEL-test pattern).
"""

from __future__ import annotations

import backend.core.crypto as crypto_mod
import backend.main as main_mod
from backend.core.ipmi_service import FanWriteResult
from backend.modules import ModuleContext, get_ctx, set_ctx
from backend.modules.fanpilot import tasks as fp_tasks


class _FakeIPMI:
    """Records set_fan_mode / set_fan_speed call kwargs for assertions.

    Optional mode_result/speed_result let a test seed a rejected FanWriteResult so the
    recovery primitive's own-write rejection guard (failsafe_rejected) can be exercised;
    by default both return None (the legacy shape — recovery treats None as ok).
    """

    def __init__(
        self,
        mode_result: FanWriteResult | None = None,
        speed_result: FanWriteResult | None = None,
    ) -> None:
        self.mode_calls: list[dict] = []
        self.speed_calls: list[dict] = []
        self._mode_result = mode_result
        self._speed_result = speed_result

    async def set_fan_mode(self, host, user, password, manual, vendor="dell"):
        self.mode_calls.append({"manual": manual, "vendor": vendor})
        return self._mode_result

    async def set_fan_speed(self, host, user, password, speed_pct, vendor="dell"):
        self.speed_calls.append({"speed": speed_pct, "vendor": vendor})
        return self._speed_result


class _FakeDB:
    """In-dict get_config + recorder for execute()/commit() — no real SQLite."""

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}
        self.executed: list[tuple[str, tuple]] = []
        self.commits = 0

    async def get_config(self, key, default=None):
        return self._config.get(key, default)

    async def execute(self, sql, params=()):
        self.executed.append((sql, params))

    async def commit(self):
        self.commits += 1


class _FakeAuth:
    def get_encryption_key(self) -> bytes:
        return b"x" * 32


def _install(config: dict | None, ipmi: _FakeIPMI | None = None) -> tuple[_FakeDB, _FakeIPMI, object]:
    """Install a fake ctx + monkeypatch call-time imports. Returns (db, ipmi, prev_ctx)."""
    try:
        prev_ctx = get_ctx()
    except Exception:
        prev_ctx = None
    db = _FakeDB(config)
    ipmi = ipmi or _FakeIPMI()
    set_ctx(ModuleContext(db=db, ipmi=ipmi, ws=None, config=None))
    return db, ipmi, prev_ctx


def _marker_inserts(db: _FakeDB) -> list[tuple]:
    """The params of every command_log INSERT recorded on the fake db."""
    return [params for sql, params in db.executed if "INSERT INTO command_log" in sql]


def _enabled_updates(db: _FakeDB) -> list[tuple]:
    """The params of every 'fanpilot_enabled = 0' UPDATE recorded on the fake db."""
    return [params for sql, params in db.executed if "fanpilot_enabled = 0" in sql]


async def _run_recovery(monkeypatch, config: dict | None, ipmi: _FakeIPMI | None = None):
    db, ipmi, prev_ctx = _install(config, ipmi)
    monkeypatch.setattr(main_mod, "auth", _FakeAuth())
    monkeypatch.setattr(crypto_mod, "decrypt", lambda token, key: "u" if "user" in token else "p")
    ctx = get_ctx()
    try:
        await fp_tasks._recover_to_bmc_auto(
            ctx, "srv-1", "192.0.2.10", "user_enc", "pwd_enc",
            reason="offline_transition", vendor="dell",
        )
    finally:
        if prev_ctx is not None:
            set_ctx(prev_ctx)
    return db, ipmi


# === C13: recovery realigns a 'fanpilot' durable intent, never clears a 'manual' pin ===
# These assert on the EXECUTED SQL shape (the fake _FakeDB has no real WHERE evaluation):
# the realignment UPDATE must set fan_desired_mode='auto' SCOPED to the 'fanpilot' row, and
# there must be NO unconditional intent-clear that could wipe a deliberate 'manual' pin.


def _intent_realign_updates(db: _FakeDB) -> list[str]:
    """Every executed UPDATE that sets fan_desired_mode = 'auto' (the realignment statement)."""
    return [sql for sql, _ in db.executed if "fan_desired_mode = 'auto'" in sql]


async def test_recovery_realigns_fanpilot_intent(monkeypatch):
    """A genuinely-applied fixed-branch recovery realigns the 'fanpilot' durable intent.

    db.executed must contain an UPDATE that sets fan_desired_mode='auto' AND is scoped
    WHERE id=? AND fan_desired_mode='fanpilot'. Before the fix there is NO fan_desired_mode
    UPDATE at all -> RED.
    """
    db, ipmi = await _run_recovery(
        monkeypatch,
        {"fanpilot.failsafe_mode": "fixed", "fanpilot.failsafe_speed": "80"},
    )
    realign = _intent_realign_updates(db)
    assert realign, "recovery must realign fan_desired_mode for a recovered fanpilot server"
    assert any(
        "fan_desired_mode = 'auto'" in sql and "fan_desired_mode = 'fanpilot'" in sql
        for sql in realign
    ), "the realignment UPDATE must be SCOPED WHERE fan_desired_mode = 'fanpilot'"
    # The unconditional fanpilot_enabled=0 anchor still runs as a SEPARATE statement.
    assert _enabled_updates(db), "the fanpilot_enabled=0 idempotency anchor must still run"


async def test_recovery_never_unconditionally_clears_manual_pin(monkeypatch):
    """BLOCKER-2 regression guard (the GPU-cook invariant, C8/D-SR).

    A deliberate fan_desired_mode='manual' pin MUST survive recovery. Assert there is NO
    executed UPDATE that sets fan_desired_mode='auto' WITHOUT the AND fan_desired_mode='fanpilot'
    scope — i.e. no unconditional intent-clear that a real DB would apply to a 'manual' row.
    """
    db, ipmi = await _run_recovery(
        monkeypatch,
        {"fanpilot.failsafe_mode": "fixed", "fanpilot.failsafe_speed": "100"},
    )
    for sql in _intent_realign_updates(db):
        assert "fan_desired_mode = 'fanpilot'" in sql, (
            "an unscoped fan_desired_mode='auto' UPDATE would wipe a deliberate 'manual' pin "
            f"(GPU-cook regression); offending SQL: {sql!r}"
        )


async def test_recovery_skips_realign_when_failsafe_write_rejected(monkeypatch):
    """The realignment is gated on (ipmi_ok and not failsafe_rejected).

    When the fail-safe write itself is hard-rejected (doubly-rejected 0xd4), failsafe_rejected
    is True -> NO fan_desired_mode UPDATE is executed; the fanpilot_enabled=0 anchor still runs.
    """
    rejected = FanWriteResult(False, "rejected", "d4", "rsp=0xd4: Insufficient privilege level")
    ipmi = _FakeIPMI(mode_result=rejected, speed_result=rejected)
    db, ipmi = await _run_recovery(
        monkeypatch,
        {"fanpilot.failsafe_mode": "fixed", "fanpilot.failsafe_speed": "100"},
        ipmi=ipmi,
    )
    assert _intent_realign_updates(db) == [], (
        "a rejected fail-safe write must NOT realign durable intent (gated on not failsafe_rejected)"
    )
    # The unconditional anchor still persists fanpilot_enabled=0.
    assert _enabled_updates(db), "the fanpilot_enabled=0 anchor must run even on a rejected fail-safe"


async def test_fixed_branch_sets_manual_and_speed(monkeypatch):
    """fixed @ 80 -> set_fan_mode(manual=True) + set_fan_speed(80); NEVER manual=False."""
    db, ipmi = await _run_recovery(
        monkeypatch,
        {"fanpilot.failsafe_mode": "fixed", "fanpilot.failsafe_speed": "80"},
    )
    assert ipmi.mode_calls == [{"manual": True, "vendor": "dell"}]
    assert ipmi.speed_calls == [{"speed": 80, "vendor": "dell"}]
    # Must NOT restore BMC auto in the fixed branch.
    assert all(c["manual"] is True for c in ipmi.mode_calls)


async def test_bmc_auto_branch_restores_auto_only(monkeypatch):
    """bmc_auto -> set_fan_mode(manual=False); NEVER set_fan_speed (legacy behavior)."""
    db, ipmi = await _run_recovery(monkeypatch, {"fanpilot.failsafe_mode": "bmc_auto"})
    assert ipmi.mode_calls == [{"manual": False, "vendor": "dell"}]
    assert ipmi.speed_calls == []


async def test_missing_config_defaults_to_fixed_100(monkeypatch):
    """No failsafe_mode row -> safety-first default: fixed @ 100."""
    db, ipmi = await _run_recovery(monkeypatch, {})
    assert ipmi.mode_calls == [{"manual": True, "vendor": "dell"}]
    assert ipmi.speed_calls == [{"speed": 100, "vendor": "dell"}]


async def test_persistence_preserved_fixed(monkeypatch):
    """Any branch still: fanpilot_enabled=0, command_log marker (detail='auto'),
    in-memory state updated. Fixed branch -> _last_state mode=manual @ speed."""
    db, ipmi = await _run_recovery(
        monkeypatch,
        {"fanpilot.failsafe_mode": "fixed", "fanpilot.failsafe_speed": "80"},
    )
    # fanpilot_enabled=0 persisted.
    assert _enabled_updates(db), "expected an UPDATE servers SET fanpilot_enabled = 0"
    # command_log marker written; command_detail MUST stay 'auto' (FIX-03 idempotency),
    # only `result` reflects the applied action.
    inserts = _marker_inserts(db)
    assert len(inserts) == 1
    server_id, command_type, command_detail, result = inserts[0]
    assert command_type == "fan_mode"
    assert command_detail == "auto", "command_detail must remain 'auto' or startup recovery loops"
    assert "failsafe" in result and "fixed" in result
    assert db.commits >= 1
    # In-memory state reflects what was actually applied: manual @ 80.
    state = fp_tasks.get_last_state("srv-1")
    assert state["mode"] == "manual"
    assert state["speed_pct"] == 80


async def test_persistence_preserved_bmc_auto(monkeypatch):
    """bmc_auto branch -> _last_state mode=auto; marker detail still 'auto'."""
    db, ipmi = await _run_recovery(monkeypatch, {"fanpilot.failsafe_mode": "bmc_auto"})
    assert _enabled_updates(db)
    inserts = _marker_inserts(db)
    assert len(inserts) == 1
    _sid, command_type, command_detail, result = inserts[0]
    assert command_type == "fan_mode"
    assert command_detail == "auto"
    assert "auto" in result
    state = fp_tasks.get_last_state("srv-1")
    assert state["mode"] == "auto"
    assert state["speed_pct"] is None


# === D-14: monitoring-only vendors are SKIPPED in the loop (one alert, no config mutation,
# auto-resume on vendor change). These drive the REAL fanpilot_loop for N ticks against a fake
# ctx, stopping the loop from its end-of-tick sleep (the only asyncio.wait_for with timeout==30;
# recovery uses timeout=5.0) after N ticks. No real BMC / ipmitool / DB. Synthetic host
# 192.0.2.10 (RFC5737). This is the D-14 behavior: hpe/lenovo/generic are monitoring-only, so
# the loop must NOT reach the write path AND must NOT mutate fanpilot_enabled (unlike the
# write_rejected fail-safe, which does set enabled=0). ===

from datetime import datetime as _dt  # noqa: E402


def _fresh_iso() -> str:
    """A sensor timestamp 'now' so the loop's freshness gate passes."""
    return _dt.utcnow().isoformat()


class _LoopWS:
    """Records broadcast_alert + broadcast_fanpilot_status for loop-level assertions."""

    def __init__(self) -> None:
        self.alerts: list[dict] = []
        self.status: list[dict] = []

    async def broadcast_alert(self, server_id, severity, source, message, value):
        self.alerts.append(
            {"server_id": server_id, "severity": severity, "source": source,
             "message": message, "value": value}
        )

    async def broadcast_fanpilot_status(self, server_id, mode, profile, speed_pct, source_temp):
        self.status.append({"server_id": server_id, "mode": mode, "speed_pct": speed_pct})


class _LoopIPMI:
    """Fan writes always return ok — the REAL capability gate lives in ipmi_service, not this
    fake — so a monitoring-only skip is proven by set_fan_speed NOT being called, never by a
    fake refusal."""

    def __init__(self) -> None:
        self.mode_calls: list[dict] = []
        self.speed_calls: list[dict] = []

    async def set_fan_mode(self, host, user, password, manual, vendor="dell"):
        self.mode_calls.append({"manual": manual, "vendor": vendor})
        return FanWriteResult(True, "ok", None, "")

    async def set_fan_speed(self, host, user, password, speed_pct, vendor="dell"):
        self.speed_calls.append({"speed": speed_pct, "vendor": vendor})
        return FanWriteResult(True, "ok", None, "")

    async def get_sensor_readings(self, host, user, password):
        return []


class _LoopDB:
    """Fake DB for the whole loop: dispatch fetchall by SQL, fetchone -> a fresh sensor reading."""

    def __init__(self, servers: list[dict], config: dict | None = None) -> None:
        self._servers = servers
        self._config = config or {}
        self.executed: list[tuple[str, tuple]] = []
        self.commits = 0
        self.sensor_value = 50.0

    async def get_config(self, key, default=None):
        return self._config.get(key, default)

    async def set_config(self, key, value):
        self._config[key] = value

    async def fetchall(self, sql, params=()):
        if "FROM servers s" in sql:
            # Main-loop server SELECT — return the LIVE rows so a between-tick vendor
            # mutation (auto-resume test) is visible on the next tick.
            return self._servers
        # _startup_state_resume intent query -> none (no startup-resume side effects).
        return []

    async def fetchone(self, sql, params=()):
        if "FROM sensor_readings" in sql:
            return {"value": self.sensor_value, "timestamp": _fresh_iso()}
        return None

    async def execute(self, sql, params=()):
        self.executed.append((sql, params))

    async def commit(self):
        self.commits += 1


class _LoopConfig:
    class _IPMI:
        poll_interval = 60

    ipmi = _IPMI()


def _reset_loop_state() -> None:
    """Clear every per-server module map the loop touches so tests don't leak into each other."""
    for name in (
        "_last_online_state", "_controllers", "_garbage_counts", "_source_last_seen",
        "_pending_readback", "_last_commanded_speed", "_last_state", "_monitoring_only_alerted",
    ):
        m = getattr(fp_tasks, name, None)
        if isinstance(m, dict):
            m.clear()


async def _drive_loop(monkeypatch, servers, n_ticks, on_tick=None, config=None):
    """Run the REAL fanpilot_loop for exactly n_ticks, stopping from the end-of-tick sleep.

    on_tick(tick_number) runs BETWEEN ticks (from the timeout==30 sleep hook) so a test can
    mutate a server row (e.g. switch vendor to 'dell') to exercise auto-resume.
    """
    _reset_loop_state()
    db = _LoopDB(servers, config)
    ipmi = _LoopIPMI()
    ws = _LoopWS()
    try:
        prev_ctx = get_ctx()
    except Exception:
        prev_ctx = None
    set_ctx(ModuleContext(db=db, ipmi=ipmi, ws=ws, config=_LoopConfig()))
    monkeypatch.setattr(main_mod, "auth", _FakeAuth())
    monkeypatch.setattr(crypto_mod, "decrypt", lambda token, key: "u" if "user" in token else "p")

    real_wait_for = fp_tasks.asyncio.wait_for
    state = {"ticks": 0}

    async def _fake_wait_for(awaitable, timeout=None):
        if timeout == 30:  # the loop's end-of-tick sleep (recovery's wait_for uses timeout=5.0)
            if fp_tasks.asyncio.iscoroutine(awaitable):
                awaitable.close()
            state["ticks"] += 1
            if on_tick is not None:
                on_tick(state["ticks"])
            if state["ticks"] >= n_ticks:
                fp_tasks._running = False
            raise fp_tasks.asyncio.TimeoutError
        return await real_wait_for(awaitable, timeout)

    monkeypatch.setattr(fp_tasks.asyncio, "wait_for", _fake_wait_for)
    try:
        await fp_tasks.fanpilot_loop()
    finally:
        fp_tasks._running = False
        if prev_ctx is not None:
            set_ctx(prev_ctx)
    return db, ipmi, ws


def _loop_server_row(server_id="srv-mon", vendor="hpe"):
    """A fanpilot_enabled, online server row shaped like the loop's SELECT result."""
    import json as _json

    return {
        "id": server_id,
        "host": "192.0.2.10",
        "username_enc": "user_enc",
        "password_enc": "pwd_enc",
        "vendor": vendor,
        "fanpilot_profile_id": "prof-1",
        "fanpilot_enabled": 1,
        "is_online": 1,
        "curve_points": _json.dumps([{"temp": 30, "speed": 20}, {"temp": 80, "speed": 100}]),
        "hysteresis": 3.0,
        "safety_threshold": 85.0,
        "source_sensor": "CPU Temp",
        "profile_name": "Custom",
    }


async def test_monitoring_only_vendor_skipped_one_alert(monkeypatch):
    """hpe (monitoring-only) fanpilot_enabled server: the loop SKIPS the write across two ticks.

    - set_fan_speed is NEVER called (no fan write attempted)
    - broadcast_alert fires EXACTLY ONCE across the two ticks (one-shot, not per-tick spam)
    - fanpilot_enabled is NOT mutated (no 'fanpilot_enabled = 0' UPDATE) so the config stays
      reversible (auto-resume on vendor change)
    - no false 'fanpilot active' status broadcast for the skipped server
    """
    server = _loop_server_row(vendor="hpe")
    db, ipmi, ws = await _drive_loop(monkeypatch, [server], n_ticks=2)

    assert ipmi.speed_calls == [], "monitoring-only vendor must not receive a fan-speed write"
    assert len(ws.alerts) == 1, f"expected exactly ONE skip alert across two ticks, got {ws.alerts}"
    assert ws.alerts[0]["severity"] == "warning"
    assert "monitoring" in ws.alerts[0]["message"].lower()
    assert not any("fanpilot_enabled = 0" in sql for sql, _ in db.executed), (
        "a monitoring-only skip must NOT mutate fanpilot_enabled (config stays reversible)"
    )
    assert ws.status == [], "must not broadcast a false 'fanpilot active' for a skipped server"


async def test_monitoring_only_auto_resume_on_vendor_change(monkeypatch):
    """After the hpe skip, switching the vendor to 'dell' lets a later tick run the write path.

    Tick 1: vendor 'hpe' -> skip + one warning alert. Between ticks the row's vendor becomes
    'dell'. Tick 2: the normal write path runs (set_fan_speed called with vendor='dell') and the
    one-shot flag is re-armed (popped) for that server.
    """
    server = _loop_server_row(vendor="hpe")

    def _switch_to_dell(tick):
        if tick == 1:
            server["vendor"] = "dell"

    db, ipmi, ws = await _drive_loop(
        monkeypatch, [server], n_ticks=2, on_tick=_switch_to_dell
    )

    assert len(ws.alerts) == 1, f"only the hpe tick should alert; got {ws.alerts}"
    assert any(c["vendor"] == "dell" for c in ipmi.speed_calls), (
        "after switching to a fan-capable vendor the loop must resume the normal write path"
    )
    # The one-shot flag is re-armed (popped) once the vendor is fan-capable again.
    assert fp_tasks._monitoring_only_alerted.get("srv-mon") is None
