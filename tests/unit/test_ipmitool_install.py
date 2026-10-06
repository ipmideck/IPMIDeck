"""Installing ipmitool from the web UI: where it may happen, what runs, and what is refused.

The install runs a package manager as root, so most of what is pinned here is refusal: in a
container, on Windows, with the setting off, without privileges, in demo mode, without a login.
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

import backend.main as bm
from backend.core import ipmitool


@pytest.fixture(autouse=True)
def _reset_module_state():
    ipmitool.report_present()
    ipmitool._forget_sudo_answer()
    yield
    ipmitool.report_present()
    ipmitool._forget_sudo_answer()


# === Finding a vendor copy on Windows ===


def test_windows_finds_the_copy_a_dell_installer_left_off_path(tmp_path, monkeypatch):
    monkeypatch.setattr(ipmitool.platform, "system", lambda: "Windows")
    monkeypatch.setattr(ipmitool.shutil, "which", lambda name: None)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    exe = tmp_path / "Dell" / "SysMgt" / "bmc" / "ipmitool.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert ipmitool.find_ipmitool() == str(exe)
    assert ipmitool.program() == str(exe)


def test_only_windows_looks_outside_path(monkeypatch):
    monkeypatch.setattr(ipmitool.platform, "system", lambda: "Linux")
    monkeypatch.setattr(ipmitool.shutil, "which", lambda name: None)
    assert ipmitool.find_ipmitool() is None
    assert ipmitool.program() == "ipmitool"


# === Whether the app may install it ===


def _host(
    monkeypatch,
    tmp_path,
    system="Linux",
    *,
    container=False,
    root=False,
    sudo=False,
    brew=True,
    distro="ID=ubuntu\n",
):
    monkeypatch.setattr(ipmitool.platform, "system", lambda: system)
    monkeypatch.setattr(ipmitool, "_in_container", lambda: container)
    monkeypatch.setattr(ipmitool, "_is_root", lambda: root)
    monkeypatch.setattr(ipmitool, "_sudo_without_password", lambda: sudo)
    brew_path = "/usr/local/bin/brew" if brew else None
    monkeypatch.setattr(
        ipmitool.shutil, "which", lambda name: brew_path if name == "brew" else None
    )
    release = tmp_path / "os-release"
    release.write_text(distro, encoding="utf-8")
    original = ipmitool._package
    monkeypatch.setattr(ipmitool, "_package", lambda system=None: original(system, release))


@pytest.mark.parametrize(
    ("host", "allowed", "reason"),
    [
        ({"container": True, "root": True}, True, "docker"),
        ({"system": "Windows"}, True, "windows"),
        ({"distro": "ID=gentoo\n"}, True, "unsupported"),
        ({"root": True}, False, "disabled"),
        ({}, True, "no_privileges"),
        ({"system": "Darwin", "brew": False}, True, "brew_missing"),
        ({"system": "Darwin", "root": True}, True, "no_privileges"),
    ],
)
def test_the_install_is_refused_with_its_reason(monkeypatch, tmp_path, host, allowed, reason):
    _host(monkeypatch, tmp_path, **host)
    plan = ipmitool.install_plan(allowed)
    assert plan["automatic"] is False
    assert plan["reason"] == reason


@pytest.mark.parametrize(
    ("host", "elevate"),
    [({"root": True}, ()), ({"sudo": True}, ("sudo", "-n")), ({"system": "Darwin"}, ())],
)
def test_the_install_runs_when_privileged_and_allowed(monkeypatch, tmp_path, host, elevate):
    _host(monkeypatch, tmp_path, **host)
    assert ipmitool.install_plan(True) == {"automatic": True, "reason": None, "elevate": elevate}


def test_status_describes_the_install_only_while_missing(monkeypatch):
    monkeypatch.setattr(ipmitool, "find_ipmitool", lambda: None)
    monkeypatch.setattr(
        ipmitool,
        "install_plan",
        lambda allowed: {"automatic": False, "reason": "disabled", "elevate": None},
    )
    missing = ipmitool.status(demo=False)
    assert missing["install"] == {"automatic": False, "reason": "disabled"}
    assert missing["os_label"]
    assert "install" not in ipmitool.status(demo=True)


def test_windows_status_lists_where_it_looks(monkeypatch):
    monkeypatch.setattr(ipmitool.platform, "system", lambda: "Windows")
    monkeypatch.setattr(ipmitool, "find_ipmitool", lambda: None)
    monkeypatch.setattr(ipmitool, "_in_container", lambda: False)
    monkeypatch.setenv("ProgramFiles", "C:\\Program Files")
    body = ipmitool.status(demo=False)
    assert body["install"]["reason"] == "windows"
    assert any(d.endswith("bmc") for d in body["search_dirs"])


def test_the_os_label_reads_the_distribution_name(tmp_path, monkeypatch):
    monkeypatch.setattr(ipmitool.platform, "system", lambda: "Linux")
    release = tmp_path / "os-release"
    release.write_text('NAME="Ubuntu"\nPRETTY_NAME="Ubuntu 24.04 LTS"\n', encoding="utf-8")
    assert ipmitool._os_label(release) == "Ubuntu 24.04 LTS"


# === Asking sudo ===


def _sudo_on_path(monkeypatch, code=0):
    """sudo found on PATH; returns the list each probe appends its thread to."""
    probes = []

    def fake_run(argv, **kwargs):
        assert argv == ["sudo", "-n", "true"]
        probes.append(threading.get_ident())
        return SimpleNamespace(returncode=code)

    monkeypatch.setattr(
        ipmitool.shutil, "which", lambda name: "/usr/bin/sudo" if name == "sudo" else None
    )
    monkeypatch.setattr(ipmitool.subprocess, "run", fake_run)
    return probes


@pytest.mark.parametrize(("code", "answer"), [(0, True), (1, False)])
def test_the_sudo_answer_is_kept_for_a_minute(monkeypatch, code, answer):
    probes = _sudo_on_path(monkeypatch, code)
    now = [0.0]
    monkeypatch.setattr(ipmitool, "time", SimpleNamespace(monotonic=lambda: now[0]))
    assert ipmitool._sudo_without_password() is answer
    now[0] = 30.0
    assert ipmitool._sudo_without_password() is answer
    assert len(probes) == 1
    now[0] = 61.0
    assert ipmitool._sudo_without_password() is answer
    assert len(probes) == 2


async def test_an_install_asks_sudo_again_off_the_event_loop(monkeypatch):
    probes = _sudo_on_path(monkeypatch)
    assert ipmitool._sudo_without_password() is True
    assert len(probes) == 1
    monkeypatch.setattr(ipmitool.platform, "system", lambda: "Linux")
    monkeypatch.setattr(ipmitool, "_in_container", lambda: False)
    monkeypatch.setattr(ipmitool, "_is_root", lambda: False)
    monkeypatch.setattr(
        ipmitool, "_package", lambda *a, **k: ipmitool._LINUX_PACKAGES[0][1:]
    )
    monkeypatch.setattr(ipmitool, "find_ipmitool", lambda: "/usr/bin/ipmitool")
    calls = []

    async def fake_exec(*argv, **kwargs):
        calls.append(argv)
        return _Proc(0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    loop_thread = threading.get_ident()
    result = await ipmitool.install(True)
    assert result["success"] is True
    assert len(probes) == 2
    assert probes[1] != loop_thread
    assert calls[0][:2] == ("sudo", "-n")


# === Running the install ===


class _Proc:
    def __init__(self, code: int, out: bytes = b"done\n"):
        self.returncode = code
        self._out = out

    async def communicate(self):
        return self._out, None

    def kill(self):
        pass


def _run(monkeypatch, codes, found_after=True):
    calls = []
    queue = list(codes)

    async def fake_exec(*argv, **kwargs):
        calls.append(argv)
        assert kwargs["stdin"] is asyncio.subprocess.DEVNULL
        return _Proc(queue.pop(0))

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(
        ipmitool,
        "install_plan",
        lambda allowed: {"automatic": True, "reason": None, "elevate": ("sudo", "-n")},
    )
    monkeypatch.setattr(ipmitool, "_package", lambda: ipmitool._LINUX_PACKAGES[0][1:])
    found = "/usr/bin/ipmitool" if found_after else None
    monkeypatch.setattr(ipmitool, "find_ipmitool", lambda: found)
    return calls


async def test_an_install_runs_the_fixed_steps_and_rearms_the_warning(monkeypatch):
    ipmitool.report_missing()
    calls = _run(monkeypatch, [0, 0])
    result = await ipmitool.install(True)
    assert result["success"] is True
    assert calls[0] == (
        "sudo", "-n", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "update"
    )
    assert calls[1][-3:] == ("install", "-y", "ipmitool")
    assert not ipmitool.known_missing()


async def test_a_failed_step_stops_and_reports_its_output(monkeypatch):
    calls = _run(monkeypatch, [100])
    result = await ipmitool.install(True)
    assert result == {
        "success": False,
        "error_code": "ipmitool_install_failed",
        "output": "done\n",
    }
    assert len(calls) == 1


async def test_success_needs_the_program_to_be_found(monkeypatch):
    _run(monkeypatch, [0, 0], found_after=False)
    result = await ipmitool.install(True)
    assert result["error_code"] == "ipmitool_install_not_found"


async def test_a_refused_plan_runs_nothing(monkeypatch):
    calls = []

    async def fake_exec(*argv, **kwargs):  # pragma: no cover - must not be reached
        calls.append(argv)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(
        ipmitool,
        "install_plan",
        lambda allowed: {"automatic": False, "reason": "disabled", "elevate": None},
    )
    result = await ipmitool.install(False)
    assert result["error_code"] == "ipmitool_install_disabled"
    assert calls == []


# === The route ===


def test_the_route_refuses_in_demo_mode(client):
    resp = client.post("/api/system/ipmitool/install")
    assert resp.json() == {"success": False, "error_code": "ipmitool_install_demo"}


def test_the_route_refuses_without_a_login(client, monkeypatch):
    monkeypatch.setattr(bm.config, "demo", False)

    async def off():
        return False

    monkeypatch.setattr(bm.auth, "is_auth_enabled", off)
    resp = client.post("/api/system/ipmitool/install")
    assert resp.json() == {"success": False, "error_code": "ipmitool_install_needs_login"}


async def test_the_route_passes_the_configured_permission(monkeypatch):
    # Called directly: with a login required, the test client would first need a session.
    from backend.api import system_routes

    monkeypatch.setattr(bm.config, "demo", False)
    monkeypatch.setattr(bm.config.ipmi, "auto_install_ipmitool", True)

    async def on():
        return True

    monkeypatch.setattr(bm.auth, "is_auth_enabled", on)
    seen = []

    async def fake_install(allowed):
        seen.append(allowed)
        return {"success": True, "output": ""}

    monkeypatch.setattr(ipmitool, "install", fake_install)
    result = await system_routes.install_ipmitool(user="operator")
    assert result["success"] is True
    assert seen == [True]


async def test_the_config_route_asks_sudo_off_the_event_loop(monkeypatch):
    # Every page loads the config, so a sudo probe on the loop would stall fan control.
    from backend.api import system_routes

    monkeypatch.setattr(bm.config, "demo", False)
    monkeypatch.setattr(bm.config.ipmi, "auto_install_ipmitool", True)
    monkeypatch.setattr(ipmitool, "find_ipmitool", lambda: None)
    monkeypatch.setattr(ipmitool.platform, "system", lambda: "Linux")
    monkeypatch.setattr(ipmitool, "_in_container", lambda: False)
    monkeypatch.setattr(ipmitool, "_is_root", lambda: False)
    monkeypatch.setattr(
        ipmitool, "_package", lambda *a, **k: ipmitool._LINUX_PACKAGES[0][1:]
    )
    monkeypatch.setattr(ipmitool, "_os_label", lambda: "Test OS")
    asked = []

    def fake_sudo():
        asked.append(threading.get_ident())
        return False

    monkeypatch.setattr(ipmitool, "_sudo_without_password", fake_sudo)
    loop_thread = threading.get_ident()
    body = await system_routes.get_config()
    assert len(asked) == 1
    assert asked[0] != loop_thread
    assert body["ipmitool"]["install"]["reason"] == "no_privileges"


def test_the_switch_reads_quoted_false_as_off():
    from backend.core.config import IPMIConfig

    assert IPMIConfig(auto_install_ipmitool="false").auto_install_ipmitool is False
    assert IPMIConfig().auto_install_ipmitool is False
