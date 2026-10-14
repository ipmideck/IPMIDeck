"""Finding the ipmitool program, and telling the operator how to install it when it is absent."""

from __future__ import annotations

import asyncio
import hashlib
import http.client
import logging
import os
import platform
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from backend.core.i18n import t

logger = logging.getLogger("ipmideck.ipmi")

PROGRAM = "ipmitool"
ERROR_CODE = "ipmitool_missing"

# A package installed from PyPI cannot pull in a system program, and a wheel has no
# post-install hook in which to even look for one, so the first moment anything can check is
# when the app starts. Everything here exists to make that first start say plainly what is
# missing and how to get it.

# /etc/os-release ID or ID_LIKE -> the command shown to the operator, and the steps run when the
# app installs it itself. ID_LIKE carries the family for the derivatives (Mint, Pop!_OS, Rocky,
# Manjaro...), so only the roots appear. The steps are fixed argument lists, never built from
# anything a request carries, and every one runs without prompting.
_APT_ENV = ("env", "DEBIAN_FRONTEND=noninteractive")
_LINUX_PACKAGES = (
    (
        ("debian", "ubuntu"),
        "sudo apt install ipmitool",
        ((*_APT_ENV, "apt-get", "update"), (*_APT_ENV, "apt-get", "install", "-y", "ipmitool")),
    ),
    (
        ("fedora", "rhel", "centos"),
        "sudo dnf install ipmitool",
        (("dnf", "install", "-y", "ipmitool"),),
    ),
    (("arch",), "sudo pacman -S ipmitool", (("pacman", "-S", "--noconfirm", "ipmitool"),)),
    (
        ("suse", "opensuse"),
        "sudo zypper install ipmitool",
        (("zypper", "--non-interactive", "install", "ipmitool"),),
    ),
    # --no-cache fetches a fresh index, so a container or host that never ran apk update still
    # finds the package.
    (
        ("alpine",),
        "sudo apk add ipmitool",
        (("apk", "add", "--no-cache", "ipmitool"),),
    ),
)
_FREEBSD = ("sudo pkg install ipmitool", (("pkg", "install", "-y", "ipmitool"),))
_MACOS = ("brew install ipmitool", (("brew", "install", "ipmitool"),))

# Windows has no package to install, but Dell's iDRAC Tools and BMC Utility installers ship
# ipmitool.exe in their own folder without adding it to PATH. Looking there means an operator who
# installed one of them needs nothing else.
_WINDOWS_VENDOR_DIRS = (
    ("Dell", "SysMgt", "bmc"),
    ("Dell", "SysMgt", "iDRACTools", "IPMI"),
)

# What the web UI downloads and installs on Windows. Pinned: the installer runs with administrator
# rights, so only this file, from this address, with the SHA-256 Dell publishes on the download
# page, is ever used. A newer Dell release means changing the address and the checksum together.
#
# The download is a WinZip self-extractor that only unpacks into C:\OpenManage and starts nothing,
# so it is never run: the MSI inside is read straight out of the archive and installed quietly.
# That MSI has a single feature ("DRAC Command Line Tools", installed by default) which puts
# ipmitool.exe in <Program Files>\Dell\SysMgt\iDRACTools\IPMI and adds that folder to PATH.
WINDOWS_PACKAGE = {
    "name": "Dell iDRAC Tools",
    "version": "11.4.0.0",
    "file": "Dell-iDRACTools-Web-WINX64-11.4.0.0-1435_A00.exe",
    "msi": "iDRACTools_x64.msi",
    "url": (
        "https://dl.dell.com/FOLDER13988263M/1/"
        "Dell-iDRACTools-Web-WINX64-11.4.0.0-1435_A00.exe"
    ),
    "page": "https://www.dell.com/support/home/en-us/drivers/driversdetails?driverid=p05hx",
    "sha256": "dd1ba761046f6c0e739ade54c1ebe1b129b85d4d7e6ce14a34dea8f160c622ec",
    "size_mb": 32,
    "supported_os": [
        "Windows 10 (64-bit)",
        "Windows 11 (64-bit)",
        "Windows Server 2022",
        "Windows Server 2025",
    ],
}
# Dell's file is about 32 MB; anything past twice that is not the file we pinned.
_WINDOWS_PACKAGE_MAX_BYTES = 64 * 1024 * 1024
_DOWNLOAD_TIMEOUT = 600
_DOWNLOAD_READ_TIMEOUT = 60
# Dell's download network turns away clients that do not look like a browser.
_DOWNLOAD_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) IPMIDeck"
# ShellExecuteEx reports a declined administrator prompt as ERROR_CANCELLED.
_ERROR_CANCELLED = 1223
# msiexec exit codes that mean the install went through; 3010 only adds that a restart is due,
# which ipmitool does not need.
_MSI_SUCCESS = (0, 3010)
_MSI_EXIT_TEXT = {
    1602: "the install was cancelled",
    1603: "the install failed",
    1618: "another installation is already running",
    1638: "another version of Dell iDRAC Tools is already installed",
}

# Long enough for a package index refresh on a slow mirror, short enough that a hung package
# manager does not hold the install lock forever.
_INSTALL_STEP_TIMEOUT = 900
_OUTPUT_TAIL = 4000
_install_lock = asyncio.Lock()

# Set while the program is known to be missing, so a poll loop that fails every few seconds
# produces one warning per episode rather than one per attempt.
_missing_reported = False

# The install notice is worked out on every page load, and asking sudo means starting a process,
# so the answer is kept for a minute. An install asks again, because the operator may have just
# granted the rights.
_SUDO_ANSWER_TTL = 60.0
_sudo_answer: tuple[float, bool] | None = None


class IpmitoolMissingError(RuntimeError):
    """ipmitool could not be started because it is not installed or not on PATH."""

    def __init__(self) -> None:
        super().__init__(f"{PROGRAM} is not installed or not on PATH")


def host_platform() -> str:
    """'windows', 'macos', 'linux' or 'other' — what the install advice depends on."""
    system = platform.system()
    return {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}.get(system, "other")


def windows_search_dirs() -> list[str]:
    """The vendor folders searched on Windows when ipmitool is not on PATH."""
    roots = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
    dirs: list[str] = []
    for root in dict.fromkeys(r for r in roots if r):
        for parts in _WINDOWS_VENDOR_DIRS:
            dirs.append(str(Path(root, *parts)))
    return dirs


def find_ipmitool() -> str | None:
    """The path ipmitool would be started from, or None when it cannot be found."""
    found = shutil.which(PROGRAM)
    if found or host_platform() != "windows":
        return found
    for folder in windows_search_dirs():
        candidate = Path(folder) / "ipmitool.exe"
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None


def program() -> str:
    """What to start: the path found, or the bare name so a missing program fails as one."""
    return find_ipmitool() or PROGRAM


def _os_release_ids(path: Path = Path("/etc/os-release")) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    ids: set[str] = set()
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() in ("ID", "ID_LIKE"):
            ids.update(value.strip().strip("\"'").lower().split())
    return ids


def _package(
    system: str | None = None, os_release: Path = Path("/etc/os-release")
) -> tuple[str, tuple[tuple[str, ...], ...]] | None:
    """(command shown, steps run) for this host, or None when there is no single package."""
    system = system or platform.system()
    if system == "Darwin":
        return _MACOS
    if system == "FreeBSD":
        return _FREEBSD
    if system == "Linux":
        ids = _os_release_ids(os_release)
        for family, command, steps in _LINUX_PACKAGES:
            if ids.intersection(family):
                return command, steps
    return None


def install_command(
    system: str | None = None, os_release: Path = Path("/etc/os-release")
) -> str | None:
    """The shell command that installs ipmitool on this host, or None when there is no single one.

    Windows has none: no Windows package manager carries ipmitool, so nothing is suggested.
    """
    package = _package(system, os_release)
    return package[0] if package else None


def install_advice() -> str:
    """English sentences for the log: what to run, or what to do when there is no command."""
    command = install_command()
    if command:
        return f"Install it with: {command}"
    if host_platform() == "windows":
        return (
            "Install a tool that includes ipmitool.exe, such as Dell iDRAC Tools (the web UI "
            "can download and start it), or put ipmitool.exe on PATH"
        )
    return "Install the ipmitool package with your system's package manager"


def report_missing() -> None:
    """Warn once that ipmitool is missing; repeated failures stay quiet until it is found again."""
    global _missing_reported
    if _missing_reported:
        return
    _missing_reported = True
    logger.warning(
        "ipmitool was not found, so no server can be reached. %s. "
        "Then restart IPMIDeck or use 'Check again' in the web UI.",
        install_advice(),
    )


def known_missing() -> bool:
    """True while the most recent attempt to start ipmitool failed because it was not found.

    For callers that only see a structured result rather than the exception, such as the fan
    writes, which turn every failure into a FanWriteResult.
    """
    return _missing_reported


def report_present() -> None:
    """Re-arm the warning: the program started, so a later disappearance is a new episode."""
    global _missing_reported
    _missing_reported = False


def ipmi_failure(exc: BaseException, lang: str) -> dict:
    """The error fields of a route's answer to a failed IPMI command.

    A missing program gets a localized message and a stable code the UI can act on. Anything
    else keeps the message the route always returned.
    """
    if isinstance(exc, IpmitoolMissingError):
        return {"error": t(ERROR_CODE, lang), "error_code": ERROR_CODE}
    return {"error": str(exc)}


# === Installing it from the web UI ===


def _is_root() -> bool:
    geteuid = getattr(os, "geteuid", None)
    return geteuid is not None and geteuid() == 0


def _probe_sudo() -> bool:
    """Start ``sudo -n true``: ``-n`` makes it fail instead of prompting."""
    if shutil.which("sudo") is None:
        return False
    try:
        result = subprocess.run(
            ["sudo", "-n", "true"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _sudo_without_password() -> bool:
    """True when sudo runs without asking, answered from the last minute's probe when there is one.

    No lock: two page loads at the same moment at most probe twice, and the tuple is replaced
    whole.
    """
    global _sudo_answer
    cached = _sudo_answer
    if cached is not None and time.monotonic() - cached[0] < _SUDO_ANSWER_TTL:
        return cached[1]
    answer = _probe_sudo()
    _sudo_answer = (time.monotonic(), answer)
    return answer


def _forget_sudo_answer() -> None:
    """Drop the kept sudo answer, so the next question starts sudo again."""
    global _sudo_answer
    _sudo_answer = None


def _in_container() -> bool:
    from backend.core.updates import _in_container as in_container

    return in_container()


def _plan(automatic: bool, reason: str | None, elevate: tuple[str, ...] | None = None) -> dict:
    return {"automatic": automatic, "reason": reason, "elevate": elevate}


def install_plan(allowed: bool) -> dict:
    """Whether the app can install ipmitool itself here, and the reason when it cannot.

    The reasons, in the order they are decided:
    - ``docker``: the image ships it, and a container user cannot install packages anyway.
    - ``no_desktop`` (Windows): running as a service, where nobody would see the prompt.
    - ``unsupported``: no known package manager.
    - ``disabled``: ``ipmi.auto_install_ipmitool`` is off (the default).
    - ``brew_missing`` / ``no_privileges``: the package manager cannot run as this process.

    A password is never asked for: a prompt from sudo or polkit appears on the server's own
    console, not in the browser, and a password typed into a web page and handed to sudo is
    exactly the kind of secret this app must not handle. Windows is the one place a prompt is
    used: there is no package manager, so the Dell installer runs, and Windows itself asks for
    administrator confirmation on the desktop of the machine running IPMIDeck. That prompt is the
    consent, so ``ipmi.auto_install_ipmitool`` is not needed there: nothing gains administrator
    rights unless the person at that computer agrees.
    """
    if _in_container():
        return _plan(False, "docker")
    plat = host_platform()
    if plat == "windows":
        if not _windows_has_desktop():
            return _plan(False, "no_desktop")
        return _plan(True, None, ())
    if _package() is None:
        return _plan(False, "unsupported")
    if not allowed:
        return _plan(False, "disabled")
    if plat == "macos":
        # Homebrew refuses to run as root and installs as the user who owns it.
        if shutil.which("brew") is None:
            return _plan(False, "brew_missing")
        if _is_root():
            return _plan(False, "no_privileges")
        return _plan(True, None, ())
    if _is_root():
        return _plan(True, None, ())
    if _sudo_without_password():
        return _plan(True, None, ("sudo", "-n"))
    return _plan(False, "no_privileges")


def _os_label(os_release: Path = Path("/etc/os-release")) -> str:
    """A readable name for the host system, as the install dialog shows it."""
    plat = host_platform()
    if plat == "windows":
        return "Windows"
    if plat == "macos":
        return "macOS"
    try:
        for line in os_release.read_text(encoding="utf-8", errors="replace").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == "PRETTY_NAME":
                label = value.strip().strip("\"'")[:80]
                if label:
                    return label
    except OSError:
        pass
    return platform.system() or "Unknown"


def status(demo: bool, allow_install: bool = False) -> dict:
    """What the web UI needs to decide whether to show the install notice, and what it says.

    It may start sudo, so callers on the event loop run it in a worker thread.
    """
    available = demo or find_ipmitool() is not None
    result: dict = {
        "available": available,
        "install_command": install_command(),
        "platform": host_platform(),
    }
    if not available:
        # Only worked out when it matters: deciding it may start sudo to ask.
        plan = install_plan(allow_install)
        result["install"] = {"automatic": plan["automatic"], "reason": plan["reason"]}
        result["os_label"] = _os_label()
        if result["platform"] == "windows":
            result["search_dirs"] = windows_search_dirs()
            result["windows_package"] = {
                key: WINDOWS_PACKAGE[key]
                for key in ("name", "version", "url", "page", "sha256", "size_mb", "supported_os")
            }
    return result


def _tail(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")[-_OUTPUT_TAIL:]


def _failure(code: str, output: bytes = b"") -> dict:
    return {"success": False, "error_code": f"ipmitool_install_{code}", "output": _tail(output)}


async def install(allow_install: bool) -> dict:
    """Install ipmitool with this host's package manager, when the plan allows it.

    One install at a time. Every step is a fixed argument list with no shell, stdin closed so
    nothing can wait on a prompt, and a timeout. Success is judged by finding the program
    afterwards, not by the package manager's exit status alone.
    """
    if _install_lock.locked():
        return _failure("busy")
    async with _install_lock:
        # Planning may start sudo, which blocks, so it runs in a worker thread. The kept answer is
        # dropped first, because the privileges may have just been granted.
        _forget_sudo_answer()
        plan = await asyncio.to_thread(install_plan, allow_install)
        if not plan["automatic"]:
            return _failure(plan["reason"] or "unsupported")
        if host_platform() == "windows":
            return await _install_windows()
        package = _package()
        if package is None:
            return _failure("unsupported")
        output = b""
        for step in package[1]:
            argv = [*plan["elevate"], *step]
            logger.warning("Installing ipmitool: %s", " ".join(argv))
            try:
                proc = await asyncio.create_subprocess_exec(
                    *argv,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
            except OSError as exc:
                return _failure("failed", output + str(exc).encode())
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), _INSTALL_STEP_TIMEOUT)
            except asyncio.TimeoutError:
                proc.kill()
                return _failure("timeout", output)
            output += out or b""
            if proc.returncode != 0:
                logger.warning("The ipmitool install step failed (exit %s)", proc.returncode)
                return _failure("failed", output)
        found = find_ipmitool()
        if found is None:
            return _failure("not_found", output)
        report_present()
        logger.warning("ipmitool installed: %s", found)
        return {"success": True, "output": _tail(output)}


# === Installing it on Windows ===


def _windows_has_desktop() -> bool:
    """False when running as a service in session 0, where no window or prompt can be seen.

    Anything that cannot be asked is taken as yes: the install then fails visibly instead of
    being refused for a guess.
    """
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        session = wintypes.DWORD()
        if not kernel32.ProcessIdToSessionId(
            kernel32.GetCurrentProcessId(), ctypes.byref(session)
        ):
            return True
        return session.value != 0
    except (OSError, AttributeError):
        return True


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to another https address; the checksum is the real guard."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise urllib.error.URLError(f"refused a redirect to {newurl}")
        logger.info("ipmitool download: following a redirect to %s", newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_HttpsOnlyRedirects)


def _download_windows_package(dest: Path) -> str:
    """Download the pinned Dell installer to ``dest`` and return its SHA-256.

    Bounded in size and in time, so a stalled or oversized answer cannot hold the install lock.
    """
    url = WINDOWS_PACKAGE["url"]
    logger.warning("Installing ipmitool: downloading %s", url)
    request = urllib.request.Request(  # noqa: S310 — fixed https address, checksum checked after
        url, headers={"User-Agent": _DOWNLOAD_USER_AGENT}, method="GET"
    )
    digest = hashlib.sha256()
    size = 0
    deadline = time.monotonic() + _DOWNLOAD_TIMEOUT
    with _OPENER.open(request, timeout=_DOWNLOAD_READ_TIMEOUT) as response, dest.open("wb") as out:
        while chunk := response.read(64 * 1024):
            size += len(chunk)
            if size > _WINDOWS_PACKAGE_MAX_BYTES:
                raise ValueError(f"the download passed {_WINDOWS_PACKAGE_MAX_BYTES} bytes")
            if time.monotonic() > deadline:
                raise TimeoutError(f"the download took longer than {_DOWNLOAD_TIMEOUT}s")
            digest.update(chunk)
            out.write(chunk)
    return digest.hexdigest()


def _extract_msi(archive: Path, dest: Path) -> None:
    """Copy the Dell MSI out of the self-extracting download into ``dest``.

    The download is a zip behind a WinZip stub, which zipfile reads as it is. Only the one
    member is read, matched by its file name and written to a name chosen here, so no path
    inside the archive ever decides where anything lands.
    """
    wanted = WINDOWS_PACKAGE["msi"].lower()
    with zipfile.ZipFile(archive) as bundle:
        members = [
            m for m in bundle.infolist()
            if not m.is_dir() and m.filename.replace("\\", "/").rsplit("/", 1)[-1].lower() == wanted
        ]
        if not members:
            raise ValueError(f"{WINDOWS_PACKAGE['msi']} is not in the downloaded package")
        member = members[0]
        if member.file_size > _WINDOWS_PACKAGE_MAX_BYTES:
            raise ValueError(f"{member.filename} is larger than expected")
        with bundle.open(member) as source, dest.open("wb") as out:
            shutil.copyfileobj(source, out)


def _read_msi_log(path: Path) -> str:
    """The end of the msiexec log, which it writes in UTF-16; empty when there is none."""
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8"
    return raw.decode(encoding, errors="replace")[-_OUTPUT_TAIL:]


def _run_elevated(program: str, parameters: str, timeout: float) -> int | None:
    """Start ``program`` through the Windows administrator prompt and wait for it to end.

    Returns the exit code, or None when it is still running after ``timeout`` seconds (it is
    left running: it holds administrator rights this process does not have). Raises
    PermissionError when the prompt is declined.
    """
    import ctypes
    from ctypes import wintypes

    class _ShellExecuteInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", wintypes.ULONG),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIconOrMonitor", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    see_mask_nocloseprocess = 0x00000040
    see_mask_flag_no_ui = 0x00000400
    sw_hide = 0
    wait_object_0 = 0

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_ShellExecuteInfo)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = see_mask_nocloseprocess | see_mask_flag_no_ui
    info.lpVerb = "runas"
    info.lpFile = program
    info.lpParameters = parameters
    info.nShow = sw_hide
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == _ERROR_CANCELLED:
            raise PermissionError("the administrator prompt was declined")
        raise ctypes.WinError(error)
    if not info.hProcess:
        # Handed to an already running instance: nothing to wait on.
        return 0
    try:
        if kernel32.WaitForSingleObject(info.hProcess, int(timeout * 1000)) != wait_object_0:
            return None
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return code.value
    finally:
        kernel32.CloseHandle(info.hProcess)


def _msiexec() -> str:
    """msiexec by its full path, so nothing on PATH or in the working folder can stand in."""
    system_root = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    return str(Path(system_root, "System32", "msiexec.exe"))


async def _install_windows() -> dict:
    """Download the pinned Dell package, check it, install its MSI quietly behind the prompt.

    The only thing the operator sees is Windows asking for administrator rights. Success is
    judged by finding ipmitool.exe afterwards, as on the other systems.
    """
    folder = Path(tempfile.mkdtemp(prefix="ipmideck-ipmitool-"))
    installer = folder / WINDOWS_PACKAGE["file"]
    msi = folder / WINDOWS_PACKAGE["msi"]
    log = folder / "msiexec.log"
    try:
        try:
            digest = await asyncio.to_thread(_download_windows_package, installer)
        except (OSError, ValueError, http.client.HTTPException) as exc:
            logger.warning("The ipmitool download failed: %s", exc)
            return _failure("download", str(exc).encode())
        if digest != WINDOWS_PACKAGE["sha256"]:
            logger.warning(
                "The downloaded installer does not match the pinned SHA-256 (got %s); not run",
                digest,
            )
            return _failure(
                "checksum",
                f"expected {WINDOWS_PACKAGE['sha256']}\nreceived {digest}".encode(),
            )
        try:
            await asyncio.to_thread(_extract_msi, installer, msi)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            logger.warning("The Dell package could not be unpacked: %s", exc)
            return _failure("extract", str(exc).encode())
        # The paths are this process's own temp folder, which cannot hold a quote character.
        parameters = f'/i "{msi}" /qn /norestart /l*v "{log}"'
        logger.warning("Installing ipmitool: msiexec %s, behind the administrator prompt", parameters)
        try:
            code = await asyncio.to_thread(
                _run_elevated, _msiexec(), parameters, _INSTALL_STEP_TIMEOUT
            )
        except PermissionError:
            logger.warning("The administrator prompt for the ipmitool install was declined")
            return _failure("cancelled")
        except OSError as exc:
            logger.warning("msiexec could not be started: %s", exc)
            return _failure("windows_failed", str(exc).encode())
        if code is None:
            return _failure("windows_timeout")
        meaning = _MSI_EXIT_TEXT.get(code, "")
        summary = f"msiexec exit code {code}" + (f": {meaning}" if meaning else "") + "\n"
        found = find_ipmitool()
        if found is None or code not in _MSI_SUCCESS:
            logger.warning("The Dell install ended (%s); ipmitool.exe found: %s", summary.strip(), found)
            output = (summary + _read_msi_log(log)).encode()
            return _failure("windows_not_found" if code in _MSI_SUCCESS else "windows_failed", output)
        report_present()
        logger.warning("ipmitool installed: %s", found)
        return {"success": True, "output": summary + found}
    finally:
        # msiexec may still hold the files when it was left running; it is a temp folder.
        shutil.rmtree(folder, ignore_errors=True)
