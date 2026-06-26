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

from backend.core.ipmi_service import LocalIPMIService


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


async def test_set_fan_speed_clamps_high():
    """speed_pct=150 is clamped to 100 -> hex 0x64; passed as the last _exec arg."""
    svc = LocalIPMIService()
    captured: dict = {}

    async def fake_exec(host, user, password, args):
        captured["args"] = args
        return ""

    svc._exec = fake_exec  # type: ignore[method-assign]
    await svc.set_fan_speed("h", "u", "p", 150)
    assert captured["args"][-1] == "0x64"  # 100 -> 0x64


async def test_set_fan_speed_clamps_low():
    """speed_pct=-5 is clamped to 0 -> hex 0x00."""
    svc = LocalIPMIService()
    captured: dict = {}

    async def fake_exec(host, user, password, args):
        captured["args"] = args
        return ""

    svc._exec = fake_exec  # type: ignore[method-assign]
    await svc.set_fan_speed("h", "u", "p", -5)
    assert captured["args"][-1] == "0x00"  # 0 -> 0x00


async def test_set_fan_speed_in_range_hex():
    """A mid-range speed (50) maps to 0x32 and uses the manual-fan raw command prefix."""
    svc = LocalIPMIService()
    captured: dict = {}

    async def fake_exec(host, user, password, args):
        captured["args"] = args
        return ""

    svc._exec = fake_exec  # type: ignore[method-assign]
    await svc.set_fan_speed("h", "u", "p", 50)
    assert captured["args"] == ["raw", "0x30", "0x30", "0x02", "0xff", "0x32"]


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


async def test_set_fan_mode_manual_vs_auto():
    svc = LocalIPMIService()
    calls = _stub(svc)
    await svc.set_fan_mode("h", "u", "p", manual=True)
    await svc.set_fan_mode("h", "u", "p", manual=False)
    assert calls[0] == ["raw", "0x30", "0x30", "0x01", "0x00"]  # manual
    assert calls[1] == ["raw", "0x30", "0x30", "0x01", "0x01"]  # auto


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
