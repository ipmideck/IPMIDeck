"""A missing ipmitool is named, reported once, and answered with an install hint.

Without it the first command failed with the bare OS error ("[WinError 2] The system cannot
find the file specified"), which reached the UI verbatim and printed a traceback on every
poll of every server.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

import backend.main as bm
from backend.core import ipmitool
from backend.core.i18n import t
from backend.core.ipmi_service import LocalIPMIService
from backend.core.ipmitool import IpmitoolMissingError


@pytest.fixture(autouse=True)
def _rearm_warning():
    ipmitool.report_present()
    yield
    ipmitool.report_present()


def _no_program(monkeypatch):
    async def fake_create(*args, **kwargs):
        raise FileNotFoundError(2, "The system cannot find the file specified")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)


# === The service ===


async def test_spawn_failure_raises_the_named_error(monkeypatch):
    _no_program(monkeypatch)
    with pytest.raises(IpmitoolMissingError, match="ipmitool is not installed"):
        await LocalIPMIService().get_sensor_readings("192.0.2.10", "u", "p")


async def test_warning_is_logged_once_per_episode(monkeypatch, caplog):
    _no_program(monkeypatch)
    service = LocalIPMIService()
    with caplog.at_level(logging.WARNING, logger="ipmideck.ipmi"):
        for _ in range(3):
            with pytest.raises(IpmitoolMissingError):
                await service.get_power_status("192.0.2.10", "u", "p")
    warnings = [r for r in caplog.records if "ipmitool was not found" in r.getMessage()]
    assert len(warnings) == 1
    assert not any(r.exc_info for r in caplog.records)
    assert ipmitool.known_missing()


async def test_a_successful_start_rearms_the_warning(monkeypatch):
    ipmitool.report_missing()

    class Proc:
        returncode = 0

        async def communicate(self):
            return b"Chassis Power is on\n", b""

    async def fake_create(*args, **kwargs):
        return Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    assert await LocalIPMIService().get_power_status("192.0.2.10", "u", "p") == "on"
    assert not ipmitool.known_missing()


async def test_sensor_poll_does_not_print_a_traceback(monkeypatch, caplog):
    from backend.modules.sensors import tasks

    class Ctx:
        class db:
            @staticmethod
            async def execute(*a):
                return None

            @staticmethod
            async def commit():
                return None

        ipmi = LocalIPMIService()

    import backend.core.crypto
    import backend.modules

    _no_program(monkeypatch)
    monkeypatch.setattr(backend.modules, "get_ctx", lambda: Ctx)
    monkeypatch.setattr(backend.core.crypto, "decrypt", lambda value, key: value)
    server = {"id": "s1", "host": "192.0.2.10", "username_enc": "u", "password_enc": "p"}
    with caplog.at_level(logging.DEBUG):
        for _ in range(3):
            tasks._next_retry.pop("s1", None)
            await tasks._poll_one_server(server, b"key")
    assert not any(r.exc_info for r in caplog.records)
    assert sum("ipmitool was not found" in r.getMessage() for r in caplog.records) == 1


# === Install advice ===


@pytest.mark.parametrize(
    ("os_release", "command"),
    [
        ('ID=ubuntu\nID_LIKE=debian\n', "sudo apt install ipmitool"),
        ('ID=linuxmint\nID_LIKE="ubuntu debian"\n', "sudo apt install ipmitool"),
        ('ID="rocky"\nID_LIKE="rhel centos fedora"\n', "sudo dnf install ipmitool"),
        ('ID=fedora\n', "sudo dnf install ipmitool"),
        ('ID=manjaro\nID_LIKE=arch\n', "sudo pacman -S ipmitool"),
        ('ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n', "sudo zypper install ipmitool"),
        ('ID=alpine\n', "sudo apk add ipmitool"),
        ('ID=somethingelse\n', None),
    ],
)
def test_linux_install_command_follows_the_distribution(tmp_path, os_release, command):
    path = tmp_path / "os-release"
    path.write_text(os_release, encoding="utf-8")
    assert ipmitool.install_command("Linux", path) == command


def test_install_command_on_other_systems(tmp_path):
    missing = tmp_path / "absent"
    assert ipmitool.install_command("Darwin", missing) == "brew install ipmitool"
    assert ipmitool.install_command("FreeBSD", missing) == "sudo pkg install ipmitool"
    # No Windows package manager carries an official build; never invent one.
    assert ipmitool.install_command("Windows", missing) is None
    assert ipmitool.install_command("Linux", missing) is None


def test_windows_advice_names_a_vendor_tool_not_a_package_manager(monkeypatch):
    monkeypatch.setattr(ipmitool.platform, "system", lambda: "Windows")
    advice = ipmitool.install_advice()
    assert "iDRAC Tools" in advice and "PATH" in advice


def test_status_is_available_in_demo_mode(monkeypatch):
    monkeypatch.setattr(ipmitool, "find_ipmitool", lambda: None)
    assert ipmitool.status(demo=True)["available"] is True
    assert ipmitool.status(demo=False)["available"] is False


# === Routes ===


def _routes_see_no_program(monkeypatch):
    async def missing(*args, **kwargs):
        raise IpmitoolMissingError()

    for name in ("get_power_status", "power_command", "get_sel", "get_sel_info", "clear_sel",
                 "get_fru"):
        monkeypatch.setattr(bm.ipmi_service, name, missing)


def _expected(lang="en"):
    return {"error": t("ipmitool_missing", lang), "error_code": "ipmitool_missing"}


def _first_server(client) -> str:
    return client.get("/api/servers").json()["servers"][0]["id"]


def test_connection_tests_answer_with_the_code(client, monkeypatch):
    _routes_see_no_program(monkeypatch)
    raw = client.post(
        "/api/servers/test",
        json={"host": "192.0.2.10", "username": "u", "password": "p"},
        headers={"Accept-Language": "it"},
    )
    assert raw.json() == {"success": False, **_expected("it")}
    saved = client.post(f"/api/servers/{_first_server(client)}/test")
    assert saved.json() == {"success": False, **_expected()}


def test_module_routes_answer_with_the_code(client, monkeypatch):
    _routes_see_no_program(monkeypatch)
    sid = _first_server(client)
    for method, path, body in (
        ("get", f"/api/modules/sel/{sid}/info", None),
        ("post", f"/api/modules/sel/{sid}/refresh", None),
        ("post", f"/api/modules/sel/{sid}/clear", None),
        ("post", f"/api/modules/fru/{sid}/refresh", None),
        ("post", f"/api/modules/power/{sid}/command", {"action": "on"}),
    ):
        resp = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)
        assert resp.json() == {"success": False, **_expected()}, path
    status = client.get(f"/api/modules/power/{sid}/status").json()
    assert status == {"server_id": sid, "status": "unknown", **_expected()}


def test_fan_write_says_missing_rather_than_rejected(client, monkeypatch):
    from backend.core.ipmi_service import FanWriteResult

    async def refused(*args, **kwargs):
        ipmitool.report_missing()
        return FanWriteResult(False, "transient", None, "ipmitool is not installed")

    monkeypatch.setattr(bm.ipmi_service, "set_fan_mode", refused)
    sid = _first_server(client)
    resp = client.post(f"/api/modules/fanpilot/{sid}/mode", json={"mode": "auto"})
    assert resp.json() == {"success": False, "mode": "auto", **_expected()}


def test_config_reports_the_program_state(client):
    body = client.get("/api/config").json()
    assert body["ipmitool"]["available"] is True  # the test app runs in demo mode
    assert set(body["ipmitool"]) == {"available", "install_command", "platform"}
