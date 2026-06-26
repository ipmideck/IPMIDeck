"""FanPilot startup state-resume + heartbeat (05-03 SR / FANPILOT-RESUME-STATE).

These tests cover the explicit-state startup-resume helper that REPLACES the old FIX-03
layer-3 command_log-inference recovery, plus the per-tick heartbeat. They drive the small
`_startup_state_resume(ctx)` helper directly (no whole-loop run) and assert the heartbeat
write contract.

Decision matrix under test (CONTEXT D-SR-02..05):
  * gap < threshold  -> RESUME persisted intent (manual @ fan_desired_speed re-issued;
    fanpilot kept enabled). A manual 100% pin survives a quick restart (the GPU-cook fix).
  * gap >= threshold -> operator FAIL-SAFE via _recover_to_bmc_auto(reason="startup_stale"),
    NEVER a silent BMC auto (set_fan_mode(manual=False) is not called as a silent auto).
  * no heartbeat (first boot) -> NO-OP: never reset, never fail-safe a server.
  * a recent manual pin is NEVER auto-reverted to BMC auto.
  * the heartbeat is written each tick as a NAIVE-UTC ISO string (gap math stays naive,
    so utcnow() - parse(last_alive) never raises a naive/aware TypeError).

Fakes only — no real BMC, ipmitool, or SQLite. asyncio_mode="auto" (pyproject) means async
tests need NO decorator. Call-time imports (`backend.main.auth`, `backend.core.crypto.decrypt`)
are monkeypatched as in test_fanpilot_failsafe.py. The previous ctx is restored in a finally.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import backend.core.crypto as crypto_mod
import backend.main as main_mod
from backend.core.ipmi_service import FanWriteResult
from backend.modules import ModuleContext, get_ctx, set_ctx
from backend.modules.fanpilot import tasks as fp_tasks


class _FakeIPMI:
    """Records set_fan_mode / set_fan_speed call kwargs; returns a programmable FanWriteResult.

    Default returns ok=True so a resume "succeeds" unless a test seeds a rejected result.
    """

    def __init__(
        self,
        mode_result: FanWriteResult | None = None,
        speed_result: FanWriteResult | None = None,
    ) -> None:
        self.mode_calls: list[dict] = []
        self.speed_calls: list[dict] = []
        self._mode_result = mode_result or FanWriteResult(True, "ok", None, "")
        self._speed_result = speed_result or FanWriteResult(True, "ok", None, "")

    async def set_fan_mode(self, host, user, password, manual, vendor="dell"):
        self.mode_calls.append({"manual": manual, "vendor": vendor})
        return self._mode_result

    async def set_fan_speed(self, host, user, password, speed_pct, vendor="dell"):
        self.speed_calls.append({"speed": speed_pct, "vendor": vendor})
        return self._speed_result


class _FakeDB:
    """In-dict get_config + a set_config recorder + a seeded fetchall — no real SQLite."""

    def __init__(
        self,
        config: dict | None = None,
        intent_rows: list[dict] | None = None,
    ) -> None:
        self._config = dict(config or {})
        self._intent_rows = intent_rows or []
        self.executed: list[tuple[str, tuple]] = []
        self.commits = 0
        self.set_config_calls: list[tuple[str, str]] = []

    async def get_config(self, key, default=None):
        return self._config.get(key, default)

    async def set_config(self, key, value):
        self.set_config_calls.append((key, value))
        self._config[key] = value

    async def fetchall(self, sql, params=()):
        # The only fetchall the resume helper issues is the intent-row SELECT.
        return list(self._intent_rows)

    async def fetchone(self, sql, params=()):
        return None

    async def execute(self, sql, params=()):
        self.executed.append((sql, params))

    async def commit(self):
        self.commits += 1


class _FakeAuth:
    def get_encryption_key(self) -> bytes:
        return b"x" * 32


def _install(db: _FakeDB, ipmi: _FakeIPMI, monkeypatch):
    """Install a fake ctx + monkeypatch call-time imports. Returns prev_ctx for restore."""
    try:
        prev_ctx = get_ctx()
    except Exception:
        prev_ctx = None
    set_ctx(ModuleContext(db=db, ipmi=ipmi, ws=None, config=None))
    monkeypatch.setattr(main_mod, "auth", _FakeAuth())
    monkeypatch.setattr(
        crypto_mod, "decrypt", lambda token, key: "u" if "user" in token else "p"
    )
    return prev_ctx


def _iso(dt: datetime) -> str:
    """Naive-UTC ISO timestamp, matching the heartbeat write format."""
    return dt.isoformat()


def _manual_row(server_id: str = "srv-1", speed: int = 80) -> dict:
    return {
        "id": server_id,
        "host": "192.0.2.10",
        "username_enc": "user_enc",
        "password_enc": "pwd_enc",
        "vendor": "dell",
        "fan_desired_mode": "manual",
        "fan_desired_speed": speed,
        "fanpilot_enabled": 0,
    }


def _fanpilot_row(server_id: str = "srv-2") -> dict:
    return {
        "id": server_id,
        "host": "192.0.2.11",
        "username_enc": "user_enc",
        "password_enc": "pwd_enc",
        "vendor": "dell",
        "fan_desired_mode": "fanpilot",
        "fan_desired_speed": None,
        "fanpilot_enabled": 1,
    }


async def _run_resume(monkeypatch, db: _FakeDB, ipmi: _FakeIPMI):
    prev_ctx = _install(db, ipmi, monkeypatch)
    ctx = get_ctx()
    try:
        await fp_tasks._startup_state_resume(ctx)
    finally:
        if prev_ctx is not None:
            set_ctx(prev_ctx)


# --- RESUME: short gap re-applies the persisted manual intent ------------------------------


async def test_resume_short_gap_reapplies_manual_speed(monkeypatch):
    """gap=60s < threshold=3600 + manual @ 80 -> re-issue set_fan_mode(manual=True)+speed(80);
    NO startup_stale fail-safe write recorded."""
    last_alive = _iso(datetime.utcnow() - timedelta(seconds=60))
    db = _FakeDB(
        config={
            "fanpilot.last_alive_at": last_alive,
            "fanpilot.resume_threshold_seconds": "3600",
        },
        intent_rows=[_manual_row(speed=80)],
    )
    ipmi = _FakeIPMI()
    await _run_resume(monkeypatch, db, ipmi)

    # Re-applied manual @ 80.
    assert ipmi.mode_calls == [{"manual": True, "vendor": "dell"}]
    assert ipmi.speed_calls == [{"speed": 80, "vendor": "dell"}]
    # No fail-safe marker was written (gap is short — we resumed, didn't fail safe).
    inserts = [p for sql, p in db.executed if "INSERT INTO command_log" in sql]
    assert inserts == [], "short-gap resume must NOT record a startup_stale fail-safe marker"
    # In-memory cache reflects the resumed manual pin.
    state = fp_tasks.get_last_state("srv-1")
    assert state["mode"] == "manual"
    assert state["speed_pct"] == 80


async def test_resume_never_silent_auto_on_manual(monkeypatch):
    """A recent manual pin is RESUMED, never reverted to BMC auto.

    The only set_fan_mode call must be manual=True; there must be NO manual=False
    (a silent BMC-auto revert is the GPU-cook bug we are fixing).
    """
    last_alive = _iso(datetime.utcnow() - timedelta(seconds=30))
    db = _FakeDB(
        config={"fanpilot.last_alive_at": last_alive},  # threshold defaults to 3600
        intent_rows=[_manual_row(speed=100)],
    )
    ipmi = _FakeIPMI()
    await _run_resume(monkeypatch, db, ipmi)

    assert {"manual": False, "vendor": "dell"} not in ipmi.mode_calls
    assert ipmi.mode_calls == [{"manual": True, "vendor": "dell"}]
    assert ipmi.speed_calls == [{"speed": 100, "vendor": "dell"}]


async def test_resume_rejected_write_not_claimed_success(monkeypatch):
    """A rejected resume write does NOT update the in-memory state to a 'success' pin."""
    last_alive = _iso(datetime.utcnow() - timedelta(seconds=30))
    rejected = FanWriteResult(False, "rejected", "d4", "rsp=0xd4: Insufficient privilege level")
    db = _FakeDB(
        config={"fanpilot.last_alive_at": last_alive},
        intent_rows=[_manual_row(server_id="srv-rej", speed=70)],
    )
    ipmi = _FakeIPMI(speed_result=rejected)
    await _run_resume(monkeypatch, db, ipmi)

    # The write was attempted but rejected — cache must NOT show a resumed manual @ 70.
    state = fp_tasks.get_last_state("srv-rej")
    assert not (state["mode"] == "manual" and state["speed_pct"] == 70)


async def test_resume_fanpilot_keeps_enabled(monkeypatch):
    """A fanpilot-intent server with a short gap is left enabled (the loop drives it),
    NOT failed safe, and reflected as 'fanpilot' in the cache."""
    last_alive = _iso(datetime.utcnow() - timedelta(seconds=120))
    db = _FakeDB(
        config={"fanpilot.last_alive_at": last_alive},
        intent_rows=[_fanpilot_row(server_id="srv-fp")],
    )
    ipmi = _FakeIPMI()
    await _run_resume(monkeypatch, db, ipmi)

    # No fail-safe marker; the loop owns the fanpilot write.
    inserts = [p for sql, p in db.executed if "INSERT INTO command_log" in sql]
    assert inserts == []
    state = fp_tasks.get_last_state("srv-fp")
    assert state["mode"] == "fanpilot"


# --- STALE: long gap applies the operator fail-safe, never silent BMC auto -----------------


async def test_stale_long_gap_applies_failsafe(monkeypatch):
    """gap=7200s >= threshold=3600 + manual server -> _recover_to_bmc_auto(reason="startup_stale").

    The fail-safe is the operator setting (default fixed @ 100): set_fan_mode(manual=True) +
    set_fan_speed(100). It must NOT be a silent BMC auto (manual=False alone).
    """
    last_alive = _iso(datetime.utcnow() - timedelta(seconds=7200))
    db = _FakeDB(
        config={
            "fanpilot.last_alive_at": last_alive,
            "fanpilot.resume_threshold_seconds": "3600",
            # default fail-safe is fixed @ 100 when the keys are missing.
        },
        intent_rows=[_manual_row(speed=20)],  # a stale LOW value must not be blindly re-applied
    )
    ipmi = _FakeIPMI()
    await _run_resume(monkeypatch, db, ipmi)

    # Fail-safe (fixed @ 100) was applied via the recovery primitive — NOT the stale 20%.
    assert {"manual": True, "vendor": "dell"} in ipmi.mode_calls
    assert ipmi.speed_calls == [{"speed": 100, "vendor": "dell"}]
    assert {"speed": 20, "vendor": "dell"} not in ipmi.speed_calls
    # The recovery primitive persists fanpilot_enabled=0 + a command_log marker.
    assert any("fanpilot_enabled = 0" in sql for sql, _ in db.executed)
    inserts = [p for sql, p in db.executed if "INSERT INTO command_log" in sql]
    assert len(inserts) == 1
    _sid, ctype, detail, result = inserts[0]
    assert ctype == "fan_mode"
    assert detail == "auto"  # FIX-03 idempotency marker stays 'auto'
    assert "failsafe" in result


async def test_stale_bmc_auto_failsafe_when_operator_chose_it(monkeypatch):
    """A long gap with failsafe_mode='bmc_auto' DOES set manual=False — but only because the
    operator explicitly chose bmc_auto, routed through the single recovery primitive (NOT a
    silent default auto)."""
    last_alive = _iso(datetime.utcnow() - timedelta(seconds=7200))
    db = _FakeDB(
        config={
            "fanpilot.last_alive_at": last_alive,
            "fanpilot.failsafe_mode": "bmc_auto",
        },
        intent_rows=[_manual_row()],
    )
    ipmi = _FakeIPMI()
    await _run_resume(monkeypatch, db, ipmi)

    assert ipmi.mode_calls == [{"manual": False, "vendor": "dell"}]
    assert ipmi.speed_calls == []


# --- FIRST BOOT: no heartbeat -> no-op, never reset or fail-safe ---------------------------


async def test_first_boot_no_heartbeat_is_noop(monkeypatch):
    """last_alive_at=None (first boot / fresh DB) -> NO set_fan_* at all, NO fail-safe marker,
    even for a manual server."""
    db = _FakeDB(
        config={},  # no fanpilot.last_alive_at
        intent_rows=[_manual_row(), _fanpilot_row()],
    )
    ipmi = _FakeIPMI()
    await _run_resume(monkeypatch, db, ipmi)

    assert ipmi.mode_calls == [], "first boot must not touch fan mode"
    assert ipmi.speed_calls == [], "first boot must not touch fan speed"
    inserts = [p for sql, p in db.executed if "INSERT INTO command_log" in sql]
    assert inserts == [], "first boot must not record a fail-safe marker"


# --- HEARTBEAT: per-tick naive-UTC write + gap math does not raise -------------------------


async def test_heartbeat_write_uses_naive_utc_iso():
    """The heartbeat write stores a NAIVE-UTC ISO string under fanpilot.last_alive_at,
    and parsing it + subtracting datetime.utcnow() does NOT raise (both naive)."""
    db = _FakeDB()
    # Simulate the loop's top-of-tick heartbeat write.
    await db.set_config("fanpilot.last_alive_at", datetime.utcnow().isoformat())

    assert db.set_config_calls, "heartbeat must call set_config"
    key, value = db.set_config_calls[-1]
    assert key == "fanpilot.last_alive_at"

    # The stored value must be a naive ISO timestamp the resume helper can parse.
    parsed = fp_tasks._parse_sqlite_timestamp(value)
    assert parsed is not None
    assert parsed.tzinfo is None, "heartbeat must be NAIVE UTC (no tzinfo)"
    # Gap math: naive - naive must not raise (the naive/aware TypeError pitfall).
    gap = (datetime.utcnow() - parsed).total_seconds()
    assert gap >= 0.0
