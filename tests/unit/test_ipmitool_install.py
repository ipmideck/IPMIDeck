"""Installing ipmitool from the web UI: where it may happen, what runs, and what is refused.

The install runs a package manager as root, so most of what is pinned here is refusal: in a
container, with the setting off, without privileges, in demo mode, without a login. On Windows it
unpacks the pinned Dell package into the data folder instead, only after its checksum matches,
and installs nothing in Windows itself.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import subprocess
import threading
import urllib.error
import zipfile
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


def test_windows_finds_the_copy_the_web_ui_unpacked(tmp_path, monkeypatch):
    monkeypatch.setattr(ipmitool.platform, "system", lambda: "Windows")
    monkeypatch.setattr(ipmitool.shutil, "which", lambda name: None)
    monkeypatch.setenv("IPMIDECK_DATA_DIR", str(tmp_path / "data"))
    exe = tmp_path / "data" / "tools" / "ipmitool" / "ipmitool.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert ipmitool.find_ipmitool() == str(exe)


def test_windows_skips_a_dell_folder_closed_to_this_user(tmp_path, monkeypatch):
    # Dell's installer leaves SysMgt readable by administrators only: asking about the file there
    # is refused, and the search goes on instead of failing.
    closed = tmp_path / "closed" / "ipmitool.exe"
    usable = tmp_path / "usable" / "ipmitool.exe"
    usable.parent.mkdir()
    usable.write_bytes(b"")
    monkeypatch.setattr(ipmitool.platform, "system", lambda: "Windows")
    monkeypatch.setattr(ipmitool.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        ipmitool, "windows_search_dirs", lambda: [str(closed.parent), str(usable.parent)]
    )
    real_is_file = type(usable).is_file

    def is_file(self):
        if self == closed:
            raise PermissionError(5, "Access is denied")
        return real_is_file(self)

    monkeypatch.setattr(type(usable), "is_file", is_file)
    assert ipmitool.find_ipmitool() == str(usable)


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
    [
        ({"root": True}, ()),
        ({"sudo": True}, ("sudo", "-n")),
        ({"system": "Darwin"}, ()),
        # Windows needs no rights: the Dell package is only unpacked into the data folder.
        ({"system": "Windows"}, ()),
    ],
)
def test_the_install_runs_when_privileged_and_allowed(monkeypatch, tmp_path, host, elevate):
    _host(monkeypatch, tmp_path, **host)
    assert ipmitool.install_plan(True) == {"automatic": True, "reason": None, "elevate": elevate}


def test_windows_offers_the_install_without_the_switch(monkeypatch, tmp_path):
    # Nothing gains rights on Windows, so the config switch is not needed, and a service works too.
    _host(monkeypatch, tmp_path, system="Windows")
    assert ipmitool.install_plan(False) == {"automatic": True, "reason": None, "elevate": ()}


def test_alpine_installs_from_a_fresh_index_but_shows_the_usual_command(tmp_path):
    # A host or container that never ran apk update has no index to find the package in.
    release = tmp_path / "os-release"
    release.write_text("ID=alpine\n", encoding="utf-8")
    assert ipmitool._package("Linux", release) == (
        "sudo apk add ipmitool",
        (("apk", "add", "--no-cache", "ipmitool"),),
    )
    assert ipmitool.install_command("Linux", release) == "sudo apk add ipmitool"


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


def test_windows_status_lists_where_it_looks_and_what_it_downloads(monkeypatch):
    monkeypatch.setattr(ipmitool.platform, "system", lambda: "Windows")
    monkeypatch.setattr(ipmitool, "find_ipmitool", lambda: None)
    monkeypatch.setattr(ipmitool, "_in_container", lambda: False)
    monkeypatch.setenv("ProgramFiles", "C:\\Program Files")
    body = ipmitool.status(demo=False)
    assert body["install"] == {"automatic": True, "reason": None}
    assert body["search_dirs"][0] == str(ipmitool.windows_tools_dir())
    assert any(d.endswith("bmc") for d in body["search_dirs"])
    package = body["windows_package"]
    assert package["url"].startswith("https://dl.dell.com/")
    assert len(package["sha256"]) == 64
    assert "Windows 11 (64-bit)" in package["supported_os"]


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
    monkeypatch.setattr(ipmitool.platform, "system", lambda: "Linux")
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


# === Running the install on Windows ===


def _self_extractor(members: dict[str, bytes]) -> bytes:
    """A zip behind an executable stub, the way Dell's WinZip self-extractor is laid out."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, data in members.items():
            bundle.writestr(name, data)
    return b"MZ" + b"\0" * 4096 + buffer.getvalue()


_DELL_ARCHIVE = {"iDRACTools_x64.msi": b"msi-bytes", "1033.mst": b"transform", "docs/readme.txt": b""}

# Where msiexec /a leaves ipmitool.exe, laid out the way Dell's MSI unpacks.
_UNPACKED_IPMI = ("Program Files 64", "Dell", "SysMgt", "iDRACTools", "IPMI")


def _unpack_like_msiexec(target, with_ipmitool=True):
    ipmi = target.joinpath(*_UNPACKED_IPMI)
    ipmi.mkdir(parents=True)
    (ipmi / "cygwin1.dll").write_bytes(b"dll")
    (ipmi / "nested").mkdir()
    (ipmi / "nested" / "skip.txt").write_bytes(b"")
    (target / "Program Files 64" / "Dell" / "SysMgt" / "iDRACTools" / "racadm").mkdir()
    if with_ipmitool:
        (ipmi / "ipmitool.exe").write_bytes(b"exe")


def _windows(
    monkeypatch,
    tmp_path,
    *,
    digest=None,
    download_error=None,
    archive=None,
    run=0,
    with_ipmitool=True,
    version="ipmitool version 1.8.18.dell 11.4.0",
):
    """A Windows host allowed to install; returns the (msi, target) of each unpacking."""
    unpacked = []
    monkeypatch.setattr(ipmitool.platform, "system", lambda: "Windows")
    monkeypatch.setattr(ipmitool.shutil, "which", lambda name: None)
    monkeypatch.setenv("IPMIDECK_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.setattr(
        ipmitool,
        "install_plan",
        lambda allowed: {"automatic": True, "reason": None, "elevate": ()},
    )

    def fake_download(dest):
        if download_error is not None:
            raise download_error
        dest.write_bytes(archive if archive is not None else _self_extractor(_DELL_ARCHIVE))
        return digest or ipmitool.WINDOWS_PACKAGE["sha256"]

    def fake_unpack(msi, target, log):
        unpacked.append((msi, target))
        if isinstance(run, BaseException):
            raise run
        if run in (0, 3010):
            _unpack_like_msiexec(target, with_ipmitool)
        return run

    def fake_version(exe):
        if isinstance(version, BaseException):
            raise version
        return version

    async def no_package_manager(*argv, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("no package manager runs on Windows")

    monkeypatch.setattr(ipmitool, "_download_windows_package", fake_download)
    monkeypatch.setattr(ipmitool, "_unpack_msi", fake_unpack)
    monkeypatch.setattr(ipmitool, "_version_of", fake_version)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_package_manager)
    return unpacked


async def test_windows_unpacks_ipmitool_into_the_data_folder(monkeypatch, tmp_path):
    # The WinZip stub only unpacks and starts nothing, so it is never run: the MSI is taken out
    # of the archive, unpacked by msiexec, and only the folder holding ipmitool.exe is kept.
    ipmitool.report_missing()
    unpacked = _windows(monkeypatch, tmp_path)
    result = await ipmitool.install(True)
    assert result["success"] is True
    tools = tmp_path / "data" / "tools" / "ipmitool"
    assert sorted(p.name for p in tools.iterdir()) == ["cygwin1.dll", "ipmitool.exe"]
    assert ipmitool.find_ipmitool() == str(tools / "ipmitool.exe")
    assert "1.8.18.dell" in result["output"]
    msi, target = unpacked[0]
    assert msi.name == "iDRACTools_x64.msi"
    # The temporary folder with the download and the unpacked MSI is gone.
    assert not target.exists()
    assert not ipmitool.known_missing()


async def test_windows_accepts_an_unpacking_that_asks_for_a_restart(monkeypatch, tmp_path):
    _windows(monkeypatch, tmp_path, run=3010)
    result = await ipmitool.install(True)
    assert result["success"] is True


async def test_windows_replaces_an_earlier_copy(monkeypatch, tmp_path):
    old = tmp_path / "data" / "tools" / "ipmitool"
    old.mkdir(parents=True)
    (old / "stale.dll").write_bytes(b"old")
    _windows(monkeypatch, tmp_path)
    result = await ipmitool.install(True)
    assert result["success"] is True
    assert not (old / "stale.dll").exists()
    assert not old.with_name("ipmitool.new").exists()


def test_the_msi_is_unpacked_without_installing_or_any_prompt(tmp_path, monkeypatch):
    seen = []

    def fake_run(command, **kwargs):
        seen.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ipmitool.subprocess, "run", fake_run)
    monkeypatch.setenv("SystemRoot", "C:\\Windows")
    msi, target, log = tmp_path / "a.msi", tmp_path / "out dir", tmp_path / "m.log"
    assert ipmitool._unpack_msi(msi, target, log) == 0
    command, kwargs = seen[0]
    # One string, so the quotes sit around the TARGETDIR value, as msiexec wants them.
    assert isinstance(command, str)
    assert command.startswith('"C:\\Windows\\System32\\msiexec.exe" /a "')
    assert f'TARGETDIR="{target}"' in command
    assert "/qn" in command and "/i " not in command
    assert kwargs["stdin"] is ipmitool.subprocess.DEVNULL


def test_an_unpacking_that_hangs_is_reported_as_a_timeout(tmp_path, monkeypatch):
    def hang(command, **kwargs):
        raise ipmitool.subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(ipmitool.subprocess, "run", hang)
    assert ipmitool._unpack_msi(tmp_path / "a.msi", tmp_path / "t", tmp_path / "l") is None


def test_the_msi_comes_out_of_the_self_extractor_under_its_own_name(tmp_path):
    archive = tmp_path / "dell.exe"
    archive.write_bytes(_self_extractor({"windows/IDRACTOOLS_X64.MSI": b"payload"}))
    dest = tmp_path / "out.msi"
    ipmitool._extract_msi(archive, dest)
    assert dest.read_bytes() == b"payload"


async def test_windows_reports_a_package_without_the_msi(monkeypatch, tmp_path):
    unpacked = _windows(monkeypatch, tmp_path, archive=_self_extractor({"other.msi": b"x"}))
    result = await ipmitool.install(True)
    assert result["error_code"] == "ipmitool_install_extract"
    assert unpacked == []


async def test_windows_reports_a_package_that_is_not_an_archive(monkeypatch, tmp_path):
    unpacked = _windows(monkeypatch, tmp_path, archive=b"MZ not a zip at all")
    result = await ipmitool.install(True)
    assert result["error_code"] == "ipmitool_install_extract"
    assert unpacked == []


async def test_windows_never_uses_a_file_with_the_wrong_checksum(monkeypatch, tmp_path):
    unpacked = _windows(monkeypatch, tmp_path, digest="0" * 64)
    result = await ipmitool.install(True)
    assert result["error_code"] == "ipmitool_install_checksum"
    assert unpacked == []


async def test_windows_reports_a_failed_download(monkeypatch, tmp_path):
    unpacked = _windows(monkeypatch, tmp_path, download_error=OSError("no route to host"))
    result = await ipmitool.install(True)
    assert result["error_code"] == "ipmitool_install_download"
    assert "no route to host" in result["output"]
    assert unpacked == []


@pytest.mark.parametrize(
    ("options", "code"),
    [
        ({"run": OSError("bad image")}, "ipmitool_install_windows_failed"),
        ({"run": None}, "ipmitool_install_windows_timeout"),
        ({"run": 1603}, "ipmitool_install_windows_failed"),
        ({"run": 1618}, "ipmitool_install_windows_failed"),
        ({"with_ipmitool": False}, "ipmitool_install_windows_not_found"),
        # Copied, but it does not start: a DLL is missing, or it is not a program at all.
        (
            {"version": subprocess.CalledProcessError(1, "ipmitool")},
            "ipmitool_install_windows_failed",
        ),
    ],
)
async def test_windows_says_why_ipmitool_was_not_unpacked(monkeypatch, tmp_path, options, code):
    _windows(monkeypatch, tmp_path, **options)
    result = await ipmitool.install(True)
    assert result["success"] is False
    assert result["error_code"] == code


def test_windows_downloads_only_the_pinned_https_address(tmp_path, monkeypatch):
    seen = []

    class _Response:
        def __init__(self):
            self._chunks = [b"abc", b""]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, size):
            return self._chunks.pop(0)

    def fake_open(request, timeout):
        seen.append(request)
        return _Response()

    monkeypatch.setattr(ipmitool._OPENER, "open", fake_open)
    dest = tmp_path / "installer.exe"
    digest = ipmitool._download_windows_package(dest)
    assert seen[0].full_url == ipmitool.WINDOWS_PACKAGE["url"]
    assert seen[0].full_url.startswith("https://")
    assert dest.read_bytes() == b"abc"
    assert digest == hashlib.sha256(b"abc").hexdigest()


def test_windows_download_refuses_a_redirect_off_https():
    handler = ipmitool._HttpsOnlyRedirects()
    with pytest.raises(urllib.error.URLError):
        handler.redirect_request(None, None, 302, "Found", {}, "http://example.invalid/x.exe")


# === The route ===


def test_the_route_refuses_in_demo_mode(client):
    resp = client.post("/api/system/ipmitool/install")
    assert resp.json() == {"success": False, "error_code": "ipmitool_install_demo"}


def test_the_route_refuses_without_a_login(client, monkeypatch):
    monkeypatch.setattr(bm.config, "demo", False)
    monkeypatch.setattr(ipmitool.platform, "system", lambda: "Linux")

    async def off():
        return False

    monkeypatch.setattr(bm.auth, "is_auth_enabled", off)
    resp = client.post("/api/system/ipmitool/install")
    assert resp.json() == {"success": False, "error_code": "ipmitool_install_needs_login"}


async def test_the_route_lets_windows_install_without_a_login(monkeypatch):
    # Nothing gains rights there: one pinned file is unpacked into the data folder.
    from backend.api import system_routes

    monkeypatch.setattr(bm.config, "demo", False)
    monkeypatch.setattr(ipmitool.platform, "system", lambda: "Windows")

    async def off():
        return False

    monkeypatch.setattr(bm.auth, "is_auth_enabled", off)

    async def fake_install(allowed):
        return {"success": True, "output": ""}

    monkeypatch.setattr(ipmitool, "install", fake_install)
    result = await system_routes.install_ipmitool(user="operator")
    assert result["success"] is True


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
