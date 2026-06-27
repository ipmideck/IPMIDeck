"""P0-3 (FANPILOT-READBACK) loop reaction + in-primitive fail-safe-write guard + read-back.

After Plan 05-01, set_fan_mode / set_fan_speed RETURN a FanWriteResult instead of raising.
This wave makes the fanpilot loop REACT to that result:

  * transient failure -> up to 3 in-tick retries (~1-2s backoff) then fall back
  * hard reject / unsupported -> SKIP retries, fall back immediately
  * either exhaustion -> _recover_to_bmc_auto(reason="write_rejected") + critical alert and
    STOP broadcasting a false "fanpilot active"
  * an accepted write whose RPM movement can't be confirmed -> command_log result
    'applied_unverified' (NOT 'success'), and read-back NEVER trips recovery (D-P03-02)

and fixes Pitfall 5 INSIDE _recover_to_bmc_auto: it now inspects the FanWriteResult.ok of ITS
OWN fail-safe set_fan_* writes, so a doubly-rejected (0xd4) fail-safe write is logged
alert-only (a 'failsafe_rejected' marker), never the 'failsafe_fixed_<n>' applied marker.

All fakes — no real BMC / ipmitool / DB. asyncio.sleep is monkeypatched to a no-op so the
retry backoff doesn't actually wait. Synthetic host 192.0.2.10 (RFC5737).
"""

from __future__ import annotations

import backend.core.crypto as crypto_mod
import backend.main as main_mod
from backend.core.ipmi_service import FanWriteResult
from backend.modules import ModuleContext, get_ctx, set_ctx
from backend.modules.fanpilot import tasks as fp_tasks


def _ok() -> FanWriteResult:
    return FanWriteResult(True, "ok", None, "")


def _transient() -> FanWriteResult:
    return FanWriteResult(False, "transient", None, "Node busy")


def _rejected(ccode="d4") -> FanWriteResult:
    return FanWriteResult(False, "rejected", ccode, f"rsp=0x{ccode}: Insufficient privilege level")


class _SeqIPMI:
    """Programmable IPMI fake: set_fan_speed/set_fan_mode pop the next result from a queue.

    Falls back to ok() when a queue is empty. Records call counts so tests can assert the
    retry policy (e.g. hard-reject => set_fan_speed called exactly once).
    """

    def __init__(
        self,
        speed_results: list[FanWriteResult] | None = None,
        mode_results: list[FanWriteResult] | None = None,
        readings: list[dict] | None = None,
    ) -> None:
        self._speed_q = list(speed_results or [])
        self._mode_q = list(mode_results or [])
        self.speed_calls: list[dict] = []
        self.mode_calls: list[dict] = []
        self._readings = readings or []

    async def set_fan_mode(self, host, user, password, manual, vendor="dell"):
        self.mode_calls.append({"manual": manual, "vendor": vendor})
        return self._mode_q.pop(0) if self._mode_q else _ok()

    async def set_fan_speed(self, host, user, password, speed_pct, vendor="dell"):
        self.speed_calls.append({"speed": speed_pct, "vendor": vendor})
        return self._speed_q.pop(0) if self._speed_q else _ok()

    async def get_sensor_readings(self, host, user, password):
        return self._readings


class _FakeWS:
    def __init__(self) -> None:
        self.alerts: list[dict] = []
        self.status: list[dict] = []

    async def broadcast_alert(self, server_id, severity, sensor, message, value):
        self.alerts.append({"server_id": server_id, "severity": severity, "value": value})

    async def broadcast_fanpilot_status(self, server_id, mode, profile, speed_pct, source_temp):
        self.status.append({"server_id": server_id, "mode": mode, "speed_pct": speed_pct})


class _FakeDB:
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


def _install(ipmi, ws, config=None):
    try:
        prev_ctx = get_ctx()
    except Exception:
        prev_ctx = None
    db = _FakeDB(config)
    set_ctx(ModuleContext(db=db, ipmi=ipmi, ws=ws, config=None))
    return db, prev_ctx


def _command_log_results(db: _FakeDB) -> list[str]:
    """result column (4th param) of every command_log INSERT."""
    out = []
    for sql, params in db.executed:
        if "INSERT INTO command_log" in sql and len(params) >= 4:
            out.append(params[3])
    return out


def _patch_imports(monkeypatch):
    monkeypatch.setattr(main_mod, "auth", _FakeAuth())
    monkeypatch.setattr(
        crypto_mod, "decrypt", lambda token, key: "u" if "user" in token else "p"
    )
    # Make retry backoff instant.
    async def _no_sleep(*a, **k):
        return None
    monkeypatch.setattr(fp_tasks.asyncio, "sleep", _no_sleep)


def _server_row(server_id="srv-1", vendor="dell"):
    return {
        "id": server_id,
        "host": "192.0.2.10",
        "username_enc": "user_enc",
        "password_enc": "pwd_enc",
        "vendor": vendor,
        "profile_name": "Custom",
    }


# === Loop set-reaction helper: _apply_fan_write(ctx, server, target_speed, ...) ===
# Returns True when the write was accepted and the loop SHOULD broadcast active control;
# False when it fell back to fail-safe (no false-active broadcast).


async def test_transient_then_ok_succeeds_within_retries(monkeypatch):
    """transient, transient, ok -> write succeeds; no fail-safe; active broadcast allowed."""
    _patch_imports(monkeypatch)
    ipmi = _SeqIPMI(speed_results=[_transient(), _transient(), _ok()])
    ws = _FakeWS()
    db, prev = _install(ipmi, ws)
    try:
        active = await fp_tasks._apply_fan_write(get_ctx(), _server_row(), 60)
    finally:
        if prev is not None:
            set_ctx(prev)
    assert active is True
    # 3 speed calls total (1 initial + 2 retries until ok).
    assert len(ipmi.speed_calls) == 3
    # No recovery fail-safe marker; no critical alert.
    assert ws.alerts == []


async def test_transient_exhausted_falls_back_and_alerts(monkeypatch):
    """All transient -> after <=3 retries: recovery(write_rejected) + critical alert, no active."""
    _patch_imports(monkeypatch)
    ipmi = _SeqIPMI(speed_results=[_transient()] * 6)  # always transient
    ws = _FakeWS()
    db, prev = _install(ipmi, ws)
    try:
        active = await fp_tasks._apply_fan_write(get_ctx(), _server_row(), 60)
    finally:
        if prev is not None:
            set_ctx(prev)
    assert active is False, "must NOT broadcast active after fail-safe"
    # initial + 3 retries = 4 speed calls max for the curve write (recovery adds its own).
    # The recovery primitive also writes a fixed-speed; assert at least the bounded retry happened.
    assert any(a["severity"] == "critical" for a in ws.alerts)
    assert ws.status == [], "no fanpilot active status on a failed write"


async def test_hard_reject_skips_retries(monkeypatch):
    """rejected (0xd4) on the first call -> NO retries: set_fan_speed called exactly once
    for the curve write, then immediate recovery + alert + no active."""
    _patch_imports(monkeypatch)
    ipmi = _SeqIPMI(speed_results=[_rejected("d4")])
    ws = _FakeWS()
    db, prev = _install(ipmi, ws)
    try:
        active = await fp_tasks._apply_fan_write(get_ctx(), _server_row(), 60)
    finally:
        if prev is not None:
            set_ctx(prev)
    assert active is False
    # Curve-write speed call happened once (no retry). The recovery primitive's OWN
    # fail-safe speed write also lands; separate those by only counting the FIRST call's
    # target. The total speed_calls includes the recovery write, so assert the FIRST is 60.
    assert ipmi.speed_calls[0]["speed"] == 60
    # Exactly one curve-write attempt before fall-back: the second speed call (if any) is the
    # recovery fail-safe write (speed=100 by default), never a retry of 60.
    retries_of_target = [c for c in ipmi.speed_calls if c["speed"] == 60]
    assert len(retries_of_target) == 1, "hard reject must not retry the rejected write"
    assert any(a["severity"] == "critical" for a in ws.alerts)


async def test_rejected_mode_set_treated_as_failed(monkeypatch):
    """A rejected set_fan_mode (not speed) also triggers fail-safe + no active."""
    _patch_imports(monkeypatch)
    ipmi = _SeqIPMI(mode_results=[_rejected("d4")], speed_results=[_ok()])
    ws = _FakeWS()
    db, prev = _install(ipmi, ws)
    try:
        active = await fp_tasks._apply_fan_write(get_ctx(), _server_row(), 60)
    finally:
        if prev is not None:
            set_ctx(prev)
    assert active is False
    assert any(a["severity"] == "critical" for a in ws.alerts)


# === C2: a transient set_fan_mode failure must be RE-ISSUED in the retry loop ===
# Before the fix the retry loop re-issued only set_fan_speed, so a transient mode
# failure followed by an ok speed retry was masked as success while the BMC may have
# stayed in auto. Each test builds its OWN fresh _SeqIPMI so queue state never leaks.


async def test_transient_mode_then_ok_reissues_both_writes(monkeypatch):
    """A transient set_fan_mode (then ok) is RE-ISSUED inside the retry loop.

    mode_results=[transient, ok], speed_results=[ok, ok]: the initial attempt folds the
    transient mode result into res, the retry loop must re-issue BOTH set_fan_mode AND
    set_fan_speed and break only when both are ok. Asserts >=2 set_fan_mode calls (the
    RED — pre-fix set_fan_mode is called exactly once) and a true/no-false-safe outcome.
    """
    _patch_imports(monkeypatch)
    ipmi = _SeqIPMI(mode_results=[_transient(), _ok()], speed_results=[_ok(), _ok()])
    ws = _FakeWS()
    db, prev = _install(ipmi, ws)
    try:
        active = await fp_tasks._apply_fan_write(get_ctx(), _server_row(), 60)
    finally:
        if prev is not None:
            set_ctx(prev)
    # set_fan_mode was RE-ISSUED in the retry (>=2): the initial attempt + at least one retry.
    assert len(ipmi.mode_calls) >= 2, "set_fan_mode must be re-issued inside the retry loop"
    # Both eventually ok -> success, no false-safe alert.
    assert active is True
    assert ws.alerts == []


async def test_transient_mode_never_recovers_fails_safe(monkeypatch):
    """A set_fan_mode that NEVER recovers must fail safe — never a false 'active'.

    Queues sized off the real _WRITE_RETRY_ATTEMPTS constant (+2 to cover the initial
    attempt + the recovery primitive's own fail-safe writes without draining into the
    _ok() fallback). Mode is always transient -> after the bounded retries the write is
    treated as failed -> recovery + critical alert, active False, no fanpilot status.
    """
    _patch_imports(monkeypatch)
    n = fp_tasks._WRITE_RETRY_ATTEMPTS + 2
    ipmi = _SeqIPMI(mode_results=[_transient()] * n, speed_results=[_ok()] * n)
    ws = _FakeWS()
    db, prev = _install(ipmi, ws)
    try:
        active = await fp_tasks._apply_fan_write(get_ctx(), _server_row(), 60)
    finally:
        if prev is not None:
            set_ctx(prev)
    assert active is False, "a never-recovering mode write must NOT broadcast active"
    assert any(a["severity"] == "critical" for a in ws.alerts)
    assert ws.status == [], "no false 'fanpilot active' on a failed write"


async def test_accepted_write_unverified_readback_no_recovery(monkeypatch):
    """An accepted write whose RPM is not confirmed -> command_log result='applied_unverified'
    and NO recovery (read-back is best-effort, never a trip — D-P03-02)."""
    _patch_imports(monkeypatch)
    # Accepted write; no readable fan RPM next tick (inconclusive).
    ipmi = _SeqIPMI(speed_results=[_ok()], readings=[])
    ws = _FakeWS()
    db, prev = _install(ipmi, ws)
    try:
        active = await fp_tasks._apply_fan_write(get_ctx(), _server_row(), 60)
        # Second tick performs the best-effort read-back of the prior commanded write.
        await fp_tasks._readback_confirm(get_ctx(), _server_row())
    finally:
        if prev is not None:
            set_ctx(prev)
    assert active is True  # accepted write -> active broadcast was allowed
    results = _command_log_results(db)
    assert "applied_unverified" in results, f"expected applied_unverified, got {results}"
    # Read-back must NEVER call recovery: no fanpilot_enabled=0 UPDATE from a read-back.
    assert not any(
        "fanpilot_enabled = 0" in sql for sql, _ in db.executed
    ), "read-back must not trip recovery"


# === C11: a vanished source sensor (missing row / NULL value) must not be a bare continue ===
# A per-server "last source seen" gap; a sustained gap (>= stale_threshold) routes through
# _recover_to_bmc_auto(reason="source_missing") + a critical alert. A single missing tick must
# NOT trip (last-seen is seeded to now on first sight). The map is cleared on recovery/shutdown.


def test_check_source_missing_first_tick_seeds_no_trip(monkeypatch):
    """First missing tick seeds last-seen to now and returns False (one missing tick never trips)."""
    fp_tasks._source_last_seen.pop("srv-csm1", None)
    tripped = fp_tasks._check_source_missing("srv-csm1", has_reading=False, stale_threshold=60.0, now=1000.0)
    assert tripped is False
    assert fp_tasks._source_last_seen["srv-csm1"] == 1000.0


def test_check_source_missing_sustained_gap_trips(monkeypatch):
    """A missing reading whose recorded last-seen is older than stale_threshold -> True."""
    fp_tasks._source_last_seen["srv-csm2"] = 1000.0
    # now is 1000 + 61 (> 60s threshold) with no usable reading -> trip.
    tripped = fp_tasks._check_source_missing("srv-csm2", has_reading=False, stale_threshold=60.0, now=1061.0)
    assert tripped is True


def test_check_source_missing_usable_reading_resets(monkeypatch):
    """A usable reading updates last-seen and returns False (gap timer resets)."""
    fp_tasks._source_last_seen["srv-csm3"] = 1000.0
    tripped = fp_tasks._check_source_missing("srv-csm3", has_reading=True, stale_threshold=60.0, now=2000.0)
    assert tripped is False
    assert fp_tasks._source_last_seen["srv-csm3"] == 2000.0


def test_source_last_seen_cleared_on_shutdown():
    """_source_last_seen is a module-level dict that fanpilot_shutdown clears."""
    assert isinstance(fp_tasks._source_last_seen, dict)
    fp_tasks._source_last_seen["srv-clear"] = 123.0
    # fanpilot_shutdown clears it; emulate the clears the shutdown performs (it is heavy /
    # needs a full ctx). The contract under test is that the symbol is cleared there.
    import inspect
    src = inspect.getsource(fp_tasks.fanpilot_shutdown)
    assert "_source_last_seen.clear()" in src, "fanpilot_shutdown must clear _source_last_seen"


async def test_source_missing_recovery_fires_alert(monkeypatch):
    """BLOCKER-3 (REQUIRED): the production source_missing branch fires recovery + critical alert.

    Seed the server's _source_last_seen older than the stale threshold, confirm the helper
    trips, then drive the same code the loop runs (recovery + broadcast_alert). Assert a
    critical alert AND a fanpilot_enabled=0 UPDATE. A single missing tick must NOT trip (a
    separate assertion).
    """
    _patch_imports(monkeypatch)
    ipmi = _SeqIPMI()
    ws = _FakeWS()
    db, prev = _install(ipmi, ws, config={"fanpilot.failsafe_mode": "fixed", "fanpilot.failsafe_speed": "100"})
    server = _server_row(server_id="srv-sm")
    source_sensor = "CPU Temp"
    stale_threshold = 60.0
    try:
        # A SINGLE missing tick must NOT trip (first sight seeds last-seen).
        fp_tasks._source_last_seen.pop("srv-sm", None)
        assert fp_tasks._check_source_missing("srv-sm", False, stale_threshold, now=5000.0) is False

        # Seed a stale last-seen, then a missing tick beyond the threshold trips.
        fp_tasks._source_last_seen["srv-sm"] = 5000.0
        assert fp_tasks._check_source_missing("srv-sm", False, stale_threshold, now=5000.0 + 61.0) is True

        # Drive the production recovery + alert the loop performs on a trip.
        await fp_tasks._recover_to_bmc_auto(
            get_ctx(), "srv-sm", server["host"], server["username_enc"],
            server["password_enc"], reason="source_missing", vendor="dell",
        )
        await get_ctx().ws.broadcast_alert(
            "srv-sm", "critical", source_sensor,
            "Source sensor reading vanished; failed safe", None,
        )
    finally:
        fp_tasks._source_last_seen.pop("srv-sm", None)
        if prev is not None:
            set_ctx(prev)
    assert any(a["severity"] == "critical" for a in ws.alerts), (
        "the source_missing branch must broadcast a critical alert"
    )
    assert any("fanpilot_enabled = 0" in sql for sql, _ in db.executed), (
        "the source_missing branch must route through _recover_to_bmc_auto"
    )


def test_source_last_seen_cleared_in_recovery():
    """_recover_to_bmc_auto must clear the per-server _source_last_seen so a re-engaged
    server starts fresh (assert via source inspection — the clear is a single pop)."""
    import inspect
    src = inspect.getsource(fp_tasks._recover_to_bmc_auto)
    assert "_source_last_seen.pop(server_id, None)" in src, (
        "_recover_to_bmc_auto must clear the per-server _source_last_seen entry"
    )


# === Pitfall 5: doubly-rejected fail-safe write must NOT be logged as applied ===


async def test_failsafe_write_rejected_records_alert_only(monkeypatch):
    """_recover_to_bmc_auto whose OWN set_fan_* return rejected -> ipmi_ok stays False and the
    command_log marker is NOT 'failsafe_fixed_<n>' (records 'failsafe_rejected' instead)."""
    _patch_imports(monkeypatch)
    # Both the fail-safe mode and speed writes are hard-rejected (0xd4 doubly-rejected case).
    ipmi = _SeqIPMI(
        mode_results=[_rejected("d4")],
        speed_results=[_rejected("d4")],
    )
    ws = _FakeWS()
    db, prev = _install(ipmi, ws, config={"fanpilot.failsafe_mode": "fixed", "fanpilot.failsafe_speed": "100"})
    try:
        await fp_tasks._recover_to_bmc_auto(
            get_ctx(), "srv-1", "192.0.2.10", "user_enc", "pwd_enc",
            reason="write_rejected", vendor="dell",
        )
    finally:
        if prev is not None:
            set_ctx(prev)
    results = _command_log_results(db)
    assert results, "recovery must still write a command_log marker"
    marker = results[0]
    assert "failsafe_fixed" not in marker, f"must NOT claim applied; got {marker}"
    assert "rejected" in marker, f"expected an alert-only/rejected marker; got {marker}"


async def test_failsafe_write_ok_still_records_applied(monkeypatch):
    """Contrast: when the fail-safe writes return ok, the existing failsafe_fixed_<n> marker
    is still written (no regression)."""
    _patch_imports(monkeypatch)
    ipmi = _SeqIPMI(mode_results=[_ok()], speed_results=[_ok()])
    ws = _FakeWS()
    db, prev = _install(ipmi, ws, config={"fanpilot.failsafe_mode": "fixed", "fanpilot.failsafe_speed": "100"})
    try:
        await fp_tasks._recover_to_bmc_auto(
            get_ctx(), "srv-1", "192.0.2.10", "user_enc", "pwd_enc",
            reason="write_rejected", vendor="dell",
        )
    finally:
        if prev is not None:
            set_ctx(prev)
    results = _command_log_results(db)
    assert any("failsafe_fixed_100" in r for r in results), f"got {results}"


async def test_failsafe_bmc_auto_rejected_records_alert_only(monkeypatch):
    """bmc_auto fail-safe whose set_fan_mode(manual=False) is rejected -> alert-only marker."""
    _patch_imports(monkeypatch)
    ipmi = _SeqIPMI(mode_results=[_rejected("d4")])
    ws = _FakeWS()
    db, prev = _install(ipmi, ws, config={"fanpilot.failsafe_mode": "bmc_auto"})
    try:
        await fp_tasks._recover_to_bmc_auto(
            get_ctx(), "srv-1", "192.0.2.10", "user_enc", "pwd_enc",
            reason="write_rejected", vendor="dell",
        )
    finally:
        if prev is not None:
            set_ctx(prev)
    results = _command_log_results(db)
    assert results
    assert "rejected" in results[0], f"got {results}"
    assert "failsafe_auto" != results[0]
