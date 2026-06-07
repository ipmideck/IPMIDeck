"""Coverage-lift tests for LocalIPMIService command methods (REVIEWS MED #7, TEST-01).

These cover the THIN command methods (power_command validation, set_fan_speed clamp + hex)
WITHOUT a real ipmitool / BMC by either (a) relying on validation that raises BEFORE _exec,
or (b) monkeypatching the instance _exec with an async stub. The actual subprocess body
(_exec) is the only part that needs a real binary and is the lone `# pragma: no cover` target.

asyncio_mode="auto" (pyproject) => async tests need NO decorator.
"""

from __future__ import annotations

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
