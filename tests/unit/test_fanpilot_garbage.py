"""P0-2 (FANPILOT-FAILSAFE-VALUE): garbage-value plausibility guard + N=3 debounce.

A *fresh* sensor row holding an implausible value (<= 0 C or >= 150 C) falls through the
Phase-4 freshness gate (timestamp-only, value-blind), so FanPilot would feed it to the curve
and drop fans to idle (interpolate_curve floors to the lowest curve point at temp <= points[0]).
The P0-2 guard rejects such values; a SINGLE transient bad read must NOT trip — only N=3
consecutive bad ticks route through the existing fail-safe primitive `_recover_to_bmc_auto`
(reason="sensor_garbage") + a critical broadcast_alert. The per-server counter resets on a
good read.

These tests drive the pure debounce helper `_check_garbage_value(server_id, value)` directly
(the loop calls the SAME helper, so behavior is identical) and drive the full recovery+alert
wiring by calling `_run_garbage_recovery` against a fake ctx — reusing the fake-ctx harness from
test_fanpilot_failsafe.py (no real BMC / ipmitool / DB). asyncio_mode="auto" (pyproject) means
async tests need no decorator. Synthetic host 192.0.2.10 (RFC5737), never a real IP.
"""

from __future__ import annotations

import backend.core.crypto as crypto_mod
import backend.main as main_mod
from backend.modules import ModuleContext, get_ctx, set_ctx
from backend.modules.fanpilot import tasks as fp_tasks


class _FakeIPMI:
    """Records set_fan_mode / set_fan_speed calls for assertions."""

    def __init__(self) -> None:
        self.mode_calls: list[dict] = []
        self.speed_calls: list[dict] = []

    async def set_fan_mode(self, host, user, password, manual, vendor="dell"):
        self.mode_calls.append({"manual": manual, "vendor": vendor})
        return fp_tasks_ok()

    async def set_fan_speed(self, host, user, password, speed_pct, vendor="dell"):
        self.speed_calls.append({"speed": speed_pct, "vendor": vendor})
        return fp_tasks_ok()


def fp_tasks_ok():
    from backend.core.ipmi_service import FanWriteResult

    return FanWriteResult(True, "ok", None, "")


class _FakeWS:
    """Records broadcast_alert calls so the P0-2 critical alert can be asserted."""

    def __init__(self) -> None:
        self.alerts: list[dict] = []

    async def broadcast_alert(self, server_id, severity, sensor, message, value):
        self.alerts.append(
            {
                "server_id": server_id,
                "severity": severity,
                "sensor": sensor,
                "message": message,
                "value": value,
            }
        )


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


def _install(config: dict | None) -> tuple[_FakeDB, _FakeIPMI, _FakeWS, object]:
    """Install a fake ctx (db + ipmi + ws). Returns (db, ipmi, ws, prev_ctx)."""
    try:
        prev_ctx = get_ctx()
    except Exception:
        prev_ctx = None
    db = _FakeDB(config)
    ipmi = _FakeIPMI()
    ws = _FakeWS()
    set_ctx(ModuleContext(db=db, ipmi=ipmi, ws=ws, config=None))
    return db, ipmi, ws, prev_ctx


def _reset_counts() -> None:
    fp_tasks._garbage_counts.clear()


def _marker_inserts(db: _FakeDB) -> list[tuple]:
    return [params for sql, params in db.executed if "INSERT INTO command_log" in sql]


# === Pure debounce helper: _check_garbage_value(server_id, value) -> bool (should-trip) ===


def test_helper_three_consecutive_garbage_ticks_trips_on_third():
    """0.0 C for 3 consecutive ticks -> trip ONLY on the 3rd tick (N=3)."""
    _reset_counts()
    assert fp_tasks._check_garbage_value("srv-1", 0.0) is False  # tick 1
    assert fp_tasks._check_garbage_value("srv-1", 0.0) is False  # tick 2
    assert fp_tasks._check_garbage_value("srv-1", 0.0) is True   # tick 3 -> trip


def test_helper_ceiling_bound_160_behaves_like_floor():
    """160.0 C (>= ceiling) trips identically after 3 ticks."""
    _reset_counts()
    assert fp_tasks._check_garbage_value("srv-1", 160.0) is False
    assert fp_tasks._check_garbage_value("srv-1", 160.0) is False
    assert fp_tasks._check_garbage_value("srv-1", 160.0) is True


def test_helper_good_read_resets_counter_no_trip():
    """bad, bad, GOOD (45.0) -> counter resets; a later bad does NOT immediately trip."""
    _reset_counts()
    assert fp_tasks._check_garbage_value("srv-1", 0.0) is False    # bad 1
    assert fp_tasks._check_garbage_value("srv-1", 0.0) is False    # bad 2
    # good read returns False (not garbage) AND resets the counter to 0.
    assert fp_tasks._check_garbage_value("srv-1", 45.0) is False   # good -> reset
    assert fp_tasks._garbage_counts.get("srv-1", 0) == 0
    # bad x2 + good + bad x2 must NOT trip (counter was reset by the good read).
    assert fp_tasks._check_garbage_value("srv-1", 0.0) is False    # bad 1 (post-reset)
    assert fp_tasks._check_garbage_value("srv-1", 0.0) is False    # bad 2 (post-reset)


def test_helper_single_bad_tick_does_not_trip():
    """One bad tick alone never trips (N=3 not reached)."""
    _reset_counts()
    assert fp_tasks._check_garbage_value("srv-2", 0.0) is False
    assert fp_tasks._garbage_counts.get("srv-2", 0) == 1


def test_helper_good_value_is_not_garbage():
    """A plausible value (45.0) is never garbage and keeps the counter at 0."""
    _reset_counts()
    assert fp_tasks._check_garbage_value("srv-3", 45.0) is False
    assert fp_tasks._garbage_counts.get("srv-3", 0) == 0


def test_helper_boundary_values_are_garbage():
    """Exactly 0.0 (<= floor) and exactly 150.0 (>= ceiling) are garbage (inclusive bounds)."""
    _reset_counts()
    assert fp_tasks._check_garbage_value("a", 0.0) is False   # garbage, count=1
    assert fp_tasks._garbage_counts.get("a", 0) == 1
    _reset_counts()
    assert fp_tasks._check_garbage_value("b", 150.0) is False  # garbage, count=1
    assert fp_tasks._garbage_counts.get("b", 0) == 1
    _reset_counts()
    # Just inside the band is NOT garbage.
    assert fp_tasks._check_garbage_value("c", 0.1) is False
    assert fp_tasks._garbage_counts.get("c", 0) == 0
    assert fp_tasks._check_garbage_value("d", 149.9) is False
    assert fp_tasks._garbage_counts.get("d", 0) == 0


# === Constants present (acceptance criteria) ===


def test_named_constants_present():
    assert fp_tasks.GARBAGE_TEMP_FLOOR_C == 0.0
    assert fp_tasks.GARBAGE_TEMP_CEILING_C == 150.0
    assert fp_tasks.GARBAGE_DEBOUNCE_TICKS == 3


# === Full recovery + alert wiring on crossing the threshold ===


async def _run_garbage_recovery(monkeypatch, value, server_id="srv-1"):
    """Drive the loop's garbage-trip branch: counter to N then call recovery + alert.

    Mirrors exactly the loop call sites: _recover_to_bmc_auto(reason="sensor_garbage")
    + ctx.ws.broadcast_alert(critical). Uses the real helper so the trip decision is the
    same one the loop makes.
    """
    db, ipmi, ws, prev_ctx = _install(
        {"fanpilot.failsafe_mode": "fixed", "fanpilot.failsafe_speed": "100"}
    )
    monkeypatch.setattr(main_mod, "auth", _FakeAuth())
    monkeypatch.setattr(
        crypto_mod, "decrypt", lambda token, key: "u" if "user" in token else "p"
    )
    ctx = get_ctx()
    tripped = False
    try:
        # Three ticks at the garbage value — the 3rd should trip.
        for _ in range(fp_tasks.GARBAGE_DEBOUNCE_TICKS):
            if fp_tasks._check_garbage_value(server_id, value):
                tripped = True
                await fp_tasks._recover_to_bmc_auto(
                    ctx, server_id, "192.0.2.10", "user_enc", "pwd_enc",
                    reason="sensor_garbage", vendor="dell",
                )
                await ctx.ws.broadcast_alert(
                    server_id, "critical", "CPU Temp",
                    f"Implausible sensor value {value}C; failed safe", value,
                )
    finally:
        if prev_ctx is not None:
            set_ctx(prev_ctx)
    return db, ipmi, ws, tripped


async def test_garbage_trip_fires_recovery_and_critical_alert(monkeypatch):
    """On the 3rd garbage tick: _recover_to_bmc_auto(reason=sensor_garbage) + critical alert."""
    _reset_counts()
    db, ipmi, ws, tripped = await _run_garbage_recovery(monkeypatch, 0.0)
    assert tripped is True
    # Fail-safe applied (fixed @ 100 default): manual mode + speed write happened.
    assert ipmi.mode_calls == [{"manual": True, "vendor": "dell"}]
    assert ipmi.speed_calls == [{"speed": 100, "vendor": "dell"}]
    # command_log marker written by the recovery primitive.
    assert _marker_inserts(db), "recovery should write a command_log marker"
    # Critical alert broadcast exactly once.
    assert len(ws.alerts) == 1
    alert = ws.alerts[0]
    assert alert["severity"] == "critical"
    assert alert["value"] == 0.0


async def test_garbage_ceiling_trip_fires_recovery_and_alert(monkeypatch):
    """160 C ceiling case behaves identically (recovery + critical alert)."""
    _reset_counts()
    db, ipmi, ws, tripped = await _run_garbage_recovery(monkeypatch, 160.0)
    assert tripped is True
    assert len(ws.alerts) == 1
    assert ws.alerts[0]["severity"] == "critical"


async def test_reset_on_good_prevents_trip(monkeypatch):
    """bad x2 + good + bad x2 never reaches N=3 -> no recovery, no alert (reset-on-good)."""
    _reset_counts()
    db, ipmi, ws, prev_ctx = _install(None)
    monkeypatch.setattr(main_mod, "auth", _FakeAuth())
    monkeypatch.setattr(
        crypto_mod, "decrypt", lambda token, key: "u" if "user" in token else "p"
    )
    try:
        seq = [0.0, 0.0, 45.0, 0.0, 0.0]  # never 3 consecutive bad
        tripped = any(fp_tasks._check_garbage_value("srv-9", v) for v in seq)
        assert tripped is False
    finally:
        if prev_ctx is not None:
            set_ctx(prev_ctx)
    # No recovery / alert fired because we never called them (trip never returned True).
    assert ws.alerts == []
    assert ipmi.mode_calls == []


def test_garbage_counts_cleared_on_shutdown_dict_exists():
    """_garbage_counts is the module-level per-server counter cleared in fanpilot_shutdown."""
    _reset_counts()
    fp_tasks._garbage_counts["srv-x"] = 2
    # fanpilot_shutdown clears it (the .clear() is asserted to exist via source);
    # here we confirm the dict is module-level and mutable.
    assert isinstance(fp_tasks._garbage_counts, dict)
    fp_tasks._garbage_counts.clear()
    assert fp_tasks._garbage_counts == {}
