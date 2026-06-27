"""Coverage-lift tests for LocalIPMIService command methods (REVIEWS MED #7, TEST-01).

These cover the THIN command methods (power_command validation, set_fan_speed clamp + hex)
WITHOUT a real ipmitool / BMC by either (a) relying on validation that raises BEFORE _exec,
or (b) monkeypatching the instance _exec with an async stub. The actual subprocess body
(_exec) is the only part that needs a real binary and is the lone `# pragma: no cover` target.

asyncio_mode="auto" (pyproject) => async tests need NO decorator.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.core.ipmi_service import (
    FanWriteResult,
    LocalIPMIService,
    classify_ipmi_error,
)


async def test_power_command_invalid_action_raises():
    """An invalid action raises ValueError BEFORE any subprocess is spawned."""
    svc = LocalIPMIService()
    with pytest.raises(ValueError):
        # No _exec monkeypatch needed: ValueError is raised before _exec is reached,
        # so no real ipmitool runs even on a machine without it.
        await svc.power_command("h", "u", "p", "invalid")


async def test_power_command_valid_action_reaches_exec():
    """A valid action passes validation and calls _exec (stubbed); output is stripped/returned."""
    svc = LocalIPMIService()
    captured: dict = {}

    async def fake_exec(host, user, password, args):
        captured["args"] = args
        return "  Chassis Power Control: Up/On  \n"

    svc._exec = fake_exec  # type: ignore[method-assign]
    result = await svc.power_command("h", "u", "p", "on")
    assert captured["args"] == ["chassis", "power", "on"]
    assert result == "Chassis Power Control: Up/On"


async def test_set_fan_speed_clamps_high(monkeypatch):
    """speed_pct=150 is clamped to 100 -> hex 0x64; the LAST argv element of the spawn.

    Migrated off the `svc._exec` stub onto the subprocess-layer harness: set_fan_speed now
    calls `_exec_capture` (not `_exec`), so a clean rc=0 _FakeProc drives the real success
    path and `_patch_capturing_create` records the full argv (ipmitool flags + raw command)."""
    captured = _patch_capturing_create(monkeypatch, _FakeProc(rc=0, out=b"", err=b""))
    svc = LocalIPMIService()
    await svc.set_fan_speed("h", "u", "p", 150)
    assert captured["args"][-1] == "0x64"  # 100 -> 0x64


async def test_set_fan_speed_clamps_low(monkeypatch):
    """speed_pct=-5 is clamped to 0 -> hex 0x00 (last argv element of the spawn)."""
    captured = _patch_capturing_create(monkeypatch, _FakeProc(rc=0, out=b"", err=b""))
    svc = LocalIPMIService()
    await svc.set_fan_speed("h", "u", "p", -5)
    assert captured["args"][-1] == "0x00"  # 0 -> 0x00


async def test_set_fan_speed_in_range_hex(monkeypatch):
    """A mid-range speed (50) maps to 0x32 and uses the Dell manual-fan raw command tail.

    The full argv is now prefixed by the ipmitool flags, so assert the TAIL of the spawn argv."""
    captured = _patch_capturing_create(monkeypatch, _FakeProc(rc=0, out=b"", err=b""))
    svc = LocalIPMIService()
    await svc.set_fan_speed("h", "u", "p", 50)
    assert list(captured["args"][-6:]) == ["raw", "0x30", "0x30", "0x02", "0xff", "0x32"]


# === remaining thin command methods (all route through the stubbed _exec) ===


def _stub(svc, return_value: str = "") -> list:
    """Replace svc._exec with a recorder; return the list that collects each call's args."""
    calls: list = []

    async def fake_exec(host, user, password, args):
        calls.append(args)
        return return_value

    svc._exec = fake_exec  # type: ignore[method-assign]
    return calls


async def test_get_sensor_readings_calls_sdr_elist():
    svc = LocalIPMIService()
    calls = _stub(svc, "")  # empty -> _parse_sdr_elist returns []
    result = await svc.get_sensor_readings("h", "u", "p")
    assert calls == [["sdr", "elist"]]
    assert result == []


async def test_get_power_status_maps_on_off_unknown():
    svc = LocalIPMIService()
    svc._exec = _make_const("Chassis Power is on")  # type: ignore[method-assign]
    assert await svc.get_power_status("h", "u", "p") == "on"
    svc._exec = _make_const("Chassis Power is off")  # type: ignore[method-assign]
    assert await svc.get_power_status("h", "u", "p") == "off"
    svc._exec = _make_const("garbage")  # type: ignore[method-assign]
    assert await svc.get_power_status("h", "u", "p") == "unknown"


async def test_set_fan_mode_manual_vs_auto(monkeypatch):
    """Migrated to the subprocess-layer harness: set_fan_mode now calls `_exec_capture`.

    Two writes, re-patching `_patch_capturing_create` per call so each captures its own argv;
    the full spawn argv is prefixed by the ipmitool flags, so assert the raw-command TAIL."""
    svc = LocalIPMIService()
    captured_manual = _patch_capturing_create(monkeypatch, _FakeProc(rc=0, out=b"", err=b""))
    await svc.set_fan_mode("h", "u", "p", manual=True)
    captured_auto = _patch_capturing_create(monkeypatch, _FakeProc(rc=0, out=b"", err=b""))
    await svc.set_fan_mode("h", "u", "p", manual=False)
    assert list(captured_manual["args"][-5:]) == ["raw", "0x30", "0x30", "0x01", "0x00"]  # manual
    assert list(captured_auto["args"][-5:]) == ["raw", "0x30", "0x30", "0x01", "0x01"]  # auto


async def test_sel_fru_raw_clear_route_through_exec():
    svc = LocalIPMIService()
    calls = _stub(svc, "")
    await svc.get_sel("h", "u", "p")
    await svc.clear_sel("h", "u", "p")
    await svc.get_fru("h", "u", "p")
    await svc.get_sel_info("h", "u", "p")
    await svc.raw_command("h", "u", "p", ["0x06", "0x01"])
    assert ["sel", "elist"] in calls
    assert ["sel", "clear"] in calls
    assert ["fru", "print"] in calls
    assert ["sel", "info"] in calls
    assert ["raw", "0x06", "0x01"] in calls


def _make_const(value: str):
    async def fake_exec(host, user, password, args):
        return value

    return fake_exec


# === _exec kill+reap lifecycle (D-16) + error-message fallback (D-18) ===
#
# These monkeypatch asyncio.create_subprocess_exec to return a _FakeProc so NO real
# ipmitool ever runs (the R720 stays READ-ONLY). They prove _exec ALWAYS terminates and
# reaps the child on timeout AND cancellation, NEVER kills a normally-completing process,
# never swallows CancelledError, and builds a legible message from stderr OR stdout.


class _FakeProc:
    """A stand-in asyncio subprocess. `hang=True` makes communicate() block forever so the
    wait_for timeout / task cancel paths are exercised; otherwise communicate() returns the
    supplied (out, err) and sets the returncode immediately (happy / error paths)."""

    def __init__(self, *, hang: bool = False, out: bytes = b"", err: bytes = b"", rc: int = 0):
        self._hang = hang
        self._out = out
        self._err = err
        self._rc = rc
        self.returncode = None  # None until communicate() completes (mirrors asyncio proc)
        self.killed = False

    async def communicate(self):
        if self._hang:
            # Block "forever" — the caller's wait_for timeout or task.cancel() ends this.
            await asyncio.sleep(3600)
        self.returncode = self._rc
        return self._out, self._err

    def kill(self):
        self.killed = True
        # Once killed, the OS would set a returncode; reflect that so reap is a no-op.
        if self.returncode is None:
            self.returncode = -9

    async def wait(self):
        return self.returncode


def _patch_proc(monkeypatch, proc: _FakeProc) -> None:
    async def fake_create(*args, **kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)


async def test_exec_kills_on_timeout(monkeypatch):
    """A hanging child + tiny timeout raises TimeoutError AND the child is killed+reaped."""
    proc = _FakeProc(hang=True)
    _patch_proc(monkeypatch, proc)
    svc = LocalIPMIService(timeout=0)
    with pytest.raises(TimeoutError):
        await svc._exec("h", "u", "p", ["chassis", "power", "status"])
    assert proc.killed is True


async def test_exec_kills_on_cancel(monkeypatch):
    """Cancelling the _exec task propagates CancelledError (NOT swallowed) AND kills the child."""
    proc = _FakeProc(hang=True)
    _patch_proc(monkeypatch, proc)
    svc = LocalIPMIService(timeout=3600)
    task = asyncio.ensure_future(svc._exec("h", "u", "p", ["sdr", "elist"]))
    await asyncio.sleep(0.05)  # let _exec reach the awaited communicate()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert proc.killed is True


async def test_exec_happy_path_not_killed(monkeypatch):
    """A normally-completing child returns its stdout and is NEVER killed."""
    proc = _FakeProc(hang=False, out=b"happy-out", err=b"", rc=0)
    _patch_proc(monkeypatch, proc)
    svc = LocalIPMIService()
    result = await svc._exec("h", "u", "p", ["chassis", "power", "status"])
    assert result == "happy-out"
    assert proc.killed is False


async def test_exec_error_message_fallback(monkeypatch):
    """returncode!=0 with empty stderr but non-empty stdout builds the message from stdout."""
    proc = _FakeProc(hang=False, out=b"out-detail", err=b"", rc=255)
    _patch_proc(monkeypatch, proc)
    svc = LocalIPMIService()
    with pytest.raises(RuntimeError) as exc:
        await svc._exec("h", "u", "p", ["raw", "0x30", "0x30"])
    msg = str(exc.value)
    assert "out-detail" in msg
    assert "code 255" in msg


# === Rider S (SEC-IPMI-PWD-ENV): password off argv, supplied via IPMITOOL_PASSWORD env ===
#
# These prove the BMC password NEVER reaches ipmitool's argv (so it can't appear in `ps`):
# the command uses `-E` (ipmitool reads IPMITOOL_PASSWORD from the environment) and the
# password is injected per-subprocess via an os.environ.copy()-based `env=` dict that still
# carries PATH. An empty/falsy password is refused BEFORE the subprocess is ever spawned.


def _patch_capturing_create(monkeypatch, proc: _FakeProc) -> dict:
    """Monkeypatch create_subprocess_exec with a recorder; return the captured dict.

    Captures positional `args` (the argv) and `kwargs` (incl. env=) of the spawn so a test
    can assert the password is in env but not argv. kwargs were previously ignored by the
    harness; this records them.
    """
    captured: dict = {}

    async def fake_create(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    return captured


async def test_exec_env_password_not_in_argv(monkeypatch):
    """`-E` is in argv; `-P` and the password literal are NOT; password is in env + PATH preserved."""
    proc = _FakeProc(hang=False, out=b"ok", err=b"", rc=0)
    captured = _patch_capturing_create(monkeypatch, proc)
    svc = LocalIPMIService()
    await svc._exec("h", "u", "secretpw", ["raw", "0x30", "0x30"])
    args = captured["args"]
    kwargs = captured["kwargs"]
    assert "-E" in args  # ipmitool reads the password from the environment
    assert "-P" not in args  # password flag must be gone from argv
    assert "secretpw" not in args  # the secret must never appear in argv
    # Password is supplied via the per-subprocess env, and PATH is preserved (env=os.environ.copy()).
    assert kwargs["env"]["IPMITOOL_PASSWORD"] == "secretpw"
    assert "PATH" in kwargs["env"]


async def test_exec_empty_password_refused_before_spawn(monkeypatch):
    """An empty/falsy password raises RuntimeError BEFORE any subprocess is spawned."""
    spawned = {"called": False}

    async def fake_create(*args, **kwargs):
        spawned["called"] = True
        return _FakeProc(hang=False, rc=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    svc = LocalIPMIService()
    with pytest.raises(RuntimeError):
        await svc._exec("h", "u", "", ["raw", "0x30", "0x30"])
    assert spawned["called"] is False  # guard fires before spawn — never injects IPMITOOL_PASSWORD=""


# === P0-3 (FANPILOT-READBACK): classify_ipmi_error completion-code classifier ===
#
# ipmitool surfaces an IPMI completion code on stderr as `... rsp=0xNN): <text>`. The classifier
# matches the MACHINE-STABLE `rsp=0x..` token (NOT the exit code — 05-RESEARCH Pitfall 2), mapping
# the 2-hex code to ok/rejected/transient. Session-layer failures (no rsp=0x token) and TimeoutError
# are transient. An unknown ccode is treated as a hard reject so it surfaces.


def _rt(msg: str) -> RuntimeError:
    return RuntimeError(msg)


def test_classify_hard_reject_d4_insufficient_privilege():
    """rsp=0xd4 (Dell raw-fan lockout / operator privilege) → hard reject, ccode d4."""
    exc = _rt(
        "ipmitool error (code 1): Unable to send RAW command "
        "(channel=0x0 netfn=0x30 lun=0x0 cmd=0x30 rsp=0xd4): Insufficient privilege level"
    )
    res = classify_ipmi_error(exc)
    assert res.ok is False
    assert res.kind == "rejected"
    assert res.ccode == "d4"


def test_classify_hard_reject_c7_data_length():
    """rsp=0xc7 (request data length invalid) → hard reject."""
    res = classify_ipmi_error(_rt("... rsp=0xc7): Request data length invalid"))
    assert res.kind == "rejected" and res.ccode == "c7" and res.ok is False


def test_classify_hard_reject_d5_d6_family():
    """0xd5/0xd6 are part of the same lockout family → hard reject."""
    assert classify_ipmi_error(_rt("... rsp=0xd5): foo")).kind == "rejected"
    assert classify_ipmi_error(_rt("... rsp=0xd5): foo")).ccode == "d5"
    assert classify_ipmi_error(_rt("... rsp=0xd6): bar")).kind == "rejected"
    assert classify_ipmi_error(_rt("... rsp=0xd6): bar")).ccode == "d6"


def test_classify_transient_c0_node_busy():
    """rsp=0xc0 (node busy) → transient, retryable."""
    res = classify_ipmi_error(_rt("... rsp=0xc0): Node busy"))
    assert res.ok is False and res.kind == "transient" and res.ccode == "c0"


def test_classify_transient_ff_unspecified():
    """rsp=0xff (unspecified error) → transient (bounded retry then fall back)."""
    res = classify_ipmi_error(_rt("... rsp=0xff): Unspecified error"))
    assert res.kind == "transient" and res.ccode == "ff"


def test_classify_session_layer_failure_is_transient():
    """A session-establish failure has NO rsp=0x token → transient, ccode None."""
    res = classify_ipmi_error(_rt("Error: Unable to establish IPMI v2 / RMCP+ session"))
    assert res.ok is False
    assert res.kind == "transient"
    assert res.ccode is None


def test_classify_timeout_is_transient():
    """A TimeoutError → transient, ccode None (no completion code at all)."""
    res = classify_ipmi_error(TimeoutError("ipmitool timed out after 10s"))
    assert res.kind == "transient" and res.ccode is None and res.ok is False


def test_classify_unknown_ccode_treated_as_hard_reject():
    """An unknown rsp=0x9a is treated as a hard reject (surface it), carrying the ccode."""
    res = classify_ipmi_error(_rt("... rsp=0x9a): some new code"))
    assert res.kind == "rejected"
    assert res.ccode == "9a"


# === P0-3: set_fan_speed / set_fan_mode return FanWriteResult ===


async def test_set_fan_speed_returns_ok_result(monkeypatch):
    """A successful write (rc=0, no rsp token) returns FanWriteResult(ok=True, kind='ok').

    Migrated to the subprocess-layer harness: the real success path runs through
    `_exec_capture`, `_scan_write_response` finds no completion code -> ok."""
    _patch_proc(monkeypatch, _FakeProc(rc=0, out=b"", err=b""))
    svc = LocalIPMIService()
    res = await svc.set_fan_speed("h", "u", "p", 50)
    assert isinstance(res, FanWriteResult)
    assert res.ok is True
    assert res.kind == "ok"


async def test_set_fan_mode_returns_ok_result(monkeypatch):
    """set_fan_mode also returns FanWriteResult(ok=True) on a clean rc=0 success."""
    _patch_proc(monkeypatch, _FakeProc(rc=0, out=b"", err=b""))
    svc = LocalIPMIService()
    res = await svc.set_fan_mode("h", "u", "p", manual=True)
    assert res.ok is True and res.kind == "ok"


async def test_set_fan_speed_rejected_is_classified_not_raised(monkeypatch):
    """A rejected write (rc!=0, rsp=0xd4) is RETURNED as rejected/d4, NOT re-raised.

    Migrated to the harness: `_exec_capture` raises RuntimeError(stderr) on rc!=0, so the
    method's `except` runs classify_ipmi_error (the raise-then-classify path; the NEW C1
    tests additionally cover the rc=0 exit-0 variant)."""
    proc = _FakeProc(
        rc=1,
        out=b"",
        err=b"ipmitool error (code 1): ... rsp=0xd4): Insufficient privilege level",
    )
    _patch_proc(monkeypatch, proc)
    svc = LocalIPMIService()
    res = await svc.set_fan_speed("h", "u", "p", 50)
    assert res.ok is False
    assert res.kind == "rejected"
    assert res.ccode == "d4"


async def test_set_fan_speed_transient_is_classified(monkeypatch):
    """A transient failure (timeout) is returned as transient, not raised.

    Migrated to the harness: a hanging child + timeout=0 makes `_exec_capture` raise
    TimeoutError -> classify -> transient."""
    _patch_proc(monkeypatch, _FakeProc(hang=True))
    svc = LocalIPMIService(timeout=0)
    res = await svc.set_fan_speed("h", "u", "p", 50)
    assert res.ok is False and res.kind == "transient" and res.ccode is None


# === C1: exit-0 false-success regression (the gap this plan closes) ===
#
# Older ipmitool historically exits 0 even on a raw-command rejection, printing the IPMI
# completion code (`... rsp=0xNN): <text>`) on stderr OR stdout (05-RESEARCH Pitfall 2). Before
# the fix, set_fan_* only classified the EXCEPTION branch, so an exit-0 rejection returned a
# false FanWriteResult(ok=True). These drive the REAL success path via _FakeProc(rc=0) so the
# fan-write methods' completion-code scan (_scan_write_response over both streams) is exercised.


async def test_set_fan_speed_exit0_rsp_on_stderr_is_rejected(monkeypatch):
    """rc=0 but a completion code on STDERR -> set_fan_speed returns rejected/d4 (closes C1)."""
    proc = _FakeProc(
        rc=0,
        out=b"",
        err=b"Unable to send RAW command (channel=0x0 netfn=0x30 lun=0x0 cmd=0x30 "
        b"rsp=0xd4): Insufficient privilege level",
    )
    _patch_proc(monkeypatch, proc)
    svc = LocalIPMIService()
    res = await svc.set_fan_speed("h", "u", "p", 50)
    assert res.ok is False
    assert res.kind == "rejected"
    assert res.ccode == "d4"


async def test_set_fan_speed_exit0_rsp_on_stdout_is_rejected(monkeypatch):
    """Some ipmitool builds print the rsp line on STDOUT at rc=0 -> still rejected/d4."""
    proc = _FakeProc(
        rc=0,
        out=b"Unable to send RAW command (... rsp=0xd4): Insufficient privilege level",
        err=b"",
    )
    _patch_proc(monkeypatch, proc)
    svc = LocalIPMIService()
    res = await svc.set_fan_speed("h", "u", "p", 50)
    assert res.ok is False
    assert res.kind == "rejected"
    assert res.ccode == "d4"


async def test_set_fan_mode_exit0_rsp_is_rejected(monkeypatch):
    """set_fan_mode parity: rc=0 + rsp=0xc7 on stderr -> rejected/c7."""
    proc = _FakeProc(rc=0, out=b"", err=b"... rsp=0xc7): Request data length invalid")
    _patch_proc(monkeypatch, proc)
    svc = LocalIPMIService()
    res = await svc.set_fan_mode("h", "u", "p", manual=True)
    assert res.ok is False
    assert res.kind == "rejected"
    assert res.ccode == "c7"


async def test_set_fan_speed_exit0_clean_is_ok(monkeypatch):
    """Non-regression: rc=0 with NO rsp token in either stream -> ok=True (no false positive)."""
    _patch_proc(monkeypatch, _FakeProc(rc=0, out=b"", err=b""))
    svc = LocalIPMIService()
    res = await svc.set_fan_speed("h", "u", "p", 50)
    assert res.ok is True
    assert res.kind == "ok"


async def test_set_fan_speed_exit0_rsp_transient_ccode_is_transient(monkeypatch):
    """The scan feeds classify_ipmi_error: rc=0 + rsp=0xc0 (node busy) -> transient/c0."""
    proc = _FakeProc(rc=0, out=b"", err=b"... rsp=0xc0): Node busy")
    _patch_proc(monkeypatch, proc)
    svc = LocalIPMIService()
    res = await svc.set_fan_speed("h", "u", "p", 50)
    assert res.ok is False
    assert res.kind == "transient"
    assert res.ccode == "c0"


async def test_set_fan_speed_unsupported_vendor_returns_unsupported():
    """An unsupported vendor → FanWriteResult(kind='unsupported'); does NOT raise NotImplementedError."""
    svc = LocalIPMIService()
    _stub(svc)
    res = await svc.set_fan_speed("h", "u", "p", 50, vendor="hpe")
    assert res.ok is False
    assert res.kind == "unsupported"
    assert res.ccode is None


async def test_set_fan_mode_unsupported_vendor_returns_unsupported():
    """set_fan_mode on an unsupported vendor is also a non-raising kind='unsupported'."""
    svc = LocalIPMIService()
    _stub(svc)
    res = await svc.set_fan_mode("h", "u", "p", manual=True, vendor="hpe")
    assert res.ok is False and res.kind == "unsupported"


async def test_demo_set_fan_returns_ok_result():
    """The demo path also returns FanWriteResult(ok=True) so downstream .ok works in demo mode."""
    from backend.core.ipmi_demo import DemoIPMIService

    demo = DemoIPMIService()
    speed_res = await demo.set_fan_speed("h", "u", "p", 60)
    mode_res = await demo.set_fan_mode("h", "u", "p", manual=True)
    assert speed_res.ok is True and speed_res.kind == "ok"
    assert mode_res.ok is True and mode_res.kind == "ok"
