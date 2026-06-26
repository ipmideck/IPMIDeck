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
from backend.modules import ModuleContext, get_ctx, set_ctx
from backend.modules.fanpilot import tasks as fp_tasks


class _FakeIPMI:
    """Records set_fan_mode / set_fan_speed call kwargs for assertions."""

    def __init__(self) -> None:
        self.mode_calls: list[dict] = []
        self.speed_calls: list[dict] = []

    async def set_fan_mode(self, host, user, password, manual, vendor="dell"):
        self.mode_calls.append({"manual": manual, "vendor": vendor})

    async def set_fan_speed(self, host, user, password, speed_pct, vendor="dell"):
        self.speed_calls.append({"speed": speed_pct, "vendor": vendor})


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


def _install(config: dict | None) -> tuple[_FakeDB, _FakeIPMI, object]:
    """Install a fake ctx + monkeypatch call-time imports. Returns (db, ipmi, prev_ctx)."""
    try:
        prev_ctx = get_ctx()
    except Exception:
        prev_ctx = None
    db = _FakeDB(config)
    ipmi = _FakeIPMI()
    set_ctx(ModuleContext(db=db, ipmi=ipmi, ws=None, config=None))
    return db, ipmi, prev_ctx


def _marker_inserts(db: _FakeDB) -> list[tuple]:
    """The params of every command_log INSERT recorded on the fake db."""
    return [params for sql, params in db.executed if "INSERT INTO command_log" in sql]


def _enabled_updates(db: _FakeDB) -> list[tuple]:
    """The params of every 'fanpilot_enabled = 0' UPDATE recorded on the fake db."""
    return [params for sql, params in db.executed if "fanpilot_enabled = 0" in sql]


async def _run_recovery(monkeypatch, config: dict | None):
    db, ipmi, prev_ctx = _install(config)
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
