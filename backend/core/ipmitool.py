"""Finding the ipmitool program, and telling the operator how to install it when it is absent."""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import subprocess
import time
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
    (("alpine",), "sudo apk add ipmitool", (("apk", "add", "ipmitool"),)),
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
            "Install a tool that includes ipmitool.exe, such as Dell iDRAC Tools, "
            "or put ipmitool.exe on PATH"
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
    - ``windows``: no package exists; the operator installs a vendor tool instead.
    - ``unsupported``: no known package manager.
    - ``disabled``: ``ipmi.auto_install_ipmitool`` is off (the default).
    - ``brew_missing`` / ``no_privileges``: the package manager cannot run as this process.

    A password is never asked for: a prompt from sudo, polkit or UAC appears on the server's own
    console, not in the browser, and a password typed into a web page and handed to sudo is
    exactly the kind of secret this app must not handle.
    """
    if _in_container():
        return _plan(False, "docker")
    plat = host_platform()
    if plat == "windows":
        return _plan(False, "windows")
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
        package = _package()
        if not plan["automatic"] or package is None:
            return _failure(plan["reason"] or "unsupported")
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
