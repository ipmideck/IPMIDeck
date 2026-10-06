"""Installing a newer IPMIDeck from the web UI, the same way this copy was installed.

What can be done depends on the install, and most of this module is about telling the cases
apart honestly:

- a Python environment IPMIDeck can write to: pip (or uv) installs the exact version, then the
  app restarts into it. On Windows the running process holds its compiled dependencies open, so
  a small helper waits for the app to exit, installs, and the operator starts it again;
- a uv tool or a pipx install: the same, through that tool when pip is not in the environment;
- Docker: a container cannot replace its own image. Only a Watchtower the operator runs next to
  it, and named in the configuration, can; otherwise the command is shown;
- a git checkout, an editable install, a system-managed Python: the command is shown, nothing runs.

Before anything changes, the database, the encryption key and config.yaml are copied aside, so a
new version whose migrations go wrong can be undone by hand.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import sysconfig
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from backend.core.branding import VERSION
from backend.core.updates import DOCKER, GIT, PIP, is_newer, parse_version, upgrade_command

logger = logging.getLogger("ipmideck.updates")

_STEP_TIMEOUT = 900
_OUTPUT_TAIL = 4000
# Long enough for the answer to this request to reach the browser before the server goes away.
_RESTART_DELAY = 1.5


# === What this install is ===


def _dist_dir() -> Path | None:
    """The folder the installed distribution's metadata sits in, or None."""
    try:
        from importlib.metadata import distribution

        dist = distribution("ipmideck")
        located = dist.locate_file("")
        return Path(str(located)) if located else None
    except Exception:  # noqa: BLE001 — no metadata means no package install to upgrade
        return None


def _editable() -> bool:
    try:
        from importlib.metadata import distribution

        raw = distribution("ipmideck").read_text("direct_url.json")
    except Exception:  # noqa: BLE001
        return False
    if not raw:
        return False
    try:
        return bool(json.loads(raw).get("dir_info", {}).get("editable"))
    except (TypeError, ValueError, AttributeError):
        return False


def _externally_managed() -> bool:
    """PEP 668: the system Python asks not to be changed with pip."""
    if sys.prefix != sys.base_prefix:
        return False
    stdlib = sysconfig.get_path("stdlib")
    return bool(stdlib) and Path(stdlib, "EXTERNALLY-MANAGED").exists()


def _user_site(location: Path | None) -> bool:
    import site

    try:
        user = Path(site.getusersitepackages())
    except Exception:  # noqa: BLE001
        return False
    return location is not None and (location == user or user in location.parents)


def python_flavor() -> str:
    """How the Python-index install was made: uv, pipx, venv, user, system, managed or editable."""
    prefix = Path(sys.prefix)
    if _editable():
        return "editable"
    if (prefix / "uv-receipt.toml").exists():
        return "uv"
    if (prefix / "pipx_metadata.json").exists():
        return "pipx"
    if sys.prefix != sys.base_prefix:
        return "venv"
    if _externally_managed():
        return "managed"
    location = _dist_dir()
    if _user_site(location):
        return "user"
    if location is not None and not os.access(location, os.W_OK):
        return "managed"
    return "system"


def _pip_available() -> bool:
    return importlib.util.find_spec("pip") is not None


# === What can be done about it ===


@dataclass
class UpdatePlan:
    automatic: bool
    mechanism: str | None = None  # pip | uv | pipx | watchtower
    command: str | None = None
    reason: str | None = None
    restart: str | None = None  # automatic | manual | container
    argv: tuple[str, ...] = field(default=(), repr=False)
    deferred: bool = False  # run after the app exits (Windows)

    def public(self) -> dict:
        return {
            "automatic": self.automatic,
            "mechanism": self.mechanism,
            "command": self.command,
            "reason": self.reason,
            "restart": self.restart,
        }


def plan_for(
    method: str,
    version: str | None,
    *,
    watchtower: bool = False,
    can_restart: bool = False,
    can_exit: bool = False,
    platform: str = sys.platform,
    flavor: Callable[[], str] = python_flavor,
) -> UpdatePlan:
    """Decide, without running anything, how ``version`` would be installed here."""
    if not version:
        return UpdatePlan(False, reason="no_update")
    command = upgrade_command(method, version)
    if method == DOCKER:
        if watchtower:
            return UpdatePlan(True, "watchtower", command, restart="container")
        return UpdatePlan(False, command=command, reason="docker")
    if method == GIT:
        return UpdatePlan(False, command=command, reason="git")
    if method != PIP:
        return UpdatePlan(False, reason="unknown")

    kind = flavor()
    pin = f"ipmideck=={version}"
    if kind == "editable":
        return UpdatePlan(False, command=command, reason="editable")
    if kind == "managed":
        return UpdatePlan(False, command=command, reason="system_python")
    if kind == "uv":
        uv = shutil.which("uv")
        if uv is None:
            return UpdatePlan(False, command=f"uv tool install --force {pin}", reason="tool_missing")
        argv: tuple[str, ...] = (uv, "tool", "install", "--force", pin)
        mechanism = "uv"
        command = f"uv tool install --force {pin}"
    elif _pip_available():
        argv = (sys.executable, "-m", "pip", "install", "--upgrade", pin)
        if kind == "user":
            argv = (*argv[:4], "--user", *argv[4:])
        mechanism = "pip"
    elif kind == "pipx" and shutil.which("pipx"):
        argv = (shutil.which("pipx") or "pipx", "install", "--force", pin)
        mechanism = "pipx"
        command = f"pipx install --force {pin}"
    else:
        return UpdatePlan(False, command=command, reason="pip_missing")

    if platform == "win32":
        # Loaded compiled modules cannot be replaced while this process runs.
        if not can_exit:
            return UpdatePlan(False, command=command, reason="manual_only")
        return UpdatePlan(True, mechanism, command, restart="manual", argv=argv, deferred=True)
    return UpdatePlan(
        True, mechanism, command, restart="automatic" if can_restart else "manual", argv=argv
    )


# === Doing it ===


def _tail(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")[-_OUTPUT_TAIL:]


def back_up(db_path: Path, data_dir: Path, config_path: Path | None, target: str) -> Path:
    """Copy the database, the key and the configuration aside before anything changes.

    The database is copied through SQLite's own backup, so a write in progress cannot leave a
    torn copy. The copies are credential-grade, like any backup of this app, and get the same
    owner-only permissions.
    """
    from backend.core.crypto import _set_secure_permissions

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = data_dir / "backups" / f"pre-update-{VERSION}-to-{target.lstrip('v')}-{stamp}"
    folder.mkdir(parents=True, exist_ok=False)
    _set_secure_permissions(folder)
    if db_path.exists():
        source = sqlite3.connect(str(db_path))
        try:
            dest = sqlite3.connect(str(folder / db_path.name))
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()
    for extra in (data_dir / "encryption.key", config_path):
        if extra is not None and Path(extra).exists():
            shutil.copy2(extra, folder / Path(extra).name)
    for item in folder.iterdir():
        _set_secure_permissions(item)
    return folder


_HELPER = r'''
"""Waits for IPMIDeck to exit, then installs the update. Standard library only."""
import ctypes, json, subprocess, sys, time
args = json.loads(sys.argv[1])
SYNCHRONIZE = 0x00100000
handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, args["pid"])
if handle:
    ctypes.windll.kernel32.WaitForSingleObject(handle, 120000)
    ctypes.windll.kernel32.CloseHandle(handle)
time.sleep(1)
with open(args["log"], "a", encoding="utf-8") as log:
    log.write("Installing IPMIDeck %s\n" % args["target"])
    log.flush()
    try:
        code = subprocess.call(args["argv"], stdout=log, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, timeout=900)
    except Exception as exc:
        code = -1
        log.write("Could not run the installer: %r\n" % (exc,))
    log.write("Finished with exit code %s. Start IPMIDeck again with: ipmideck start\n" % code)
'''


def _post_watchtower(url: str, token: str) -> str | None:
    """Ask Watchtower to update. None when it accepted, or the error code."""
    request = urllib.request.Request(
        url.rstrip("/") + "/v1/update",
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:  # noqa: S310 — operator's URL
            return None if 200 <= resp.status < 300 else "watchtower_refused"
    except urllib.error.HTTPError as exc:
        return "watchtower_unauthorized" if exc.code in (401, 403) else "watchtower_refused"
    except (TimeoutError, ConnectionResetError):
        # Watchtower answers when the update is done, and stopping this container to replace it
        # cuts the request short. Either way it has started.
        return None
    except (urllib.error.URLError, OSError):
        return "watchtower_unreachable"


class UpdateInstaller:
    """One update at a time, with a state the web UI can poll."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._task: asyncio.Task | None = None
        self.state: dict = {"phase": "idle"}

    def snapshot(self) -> dict:
        return dict(self.state)

    def busy(self) -> bool:
        return self.state.get("phase") in ("backing_up", "installing", "restarting")

    def _set(self, **fields) -> None:
        self.state = {**self.state, **fields}

    async def start(
        self,
        *,
        plan: UpdatePlan,
        target: str,
        db_path: Path,
        data_dir: Path,
        config_path: Path | None,
        restart: Callable[[], None] | None,
        exit_app: Callable[[], None] | None,
        watchtower: tuple[str, str] | None = None,
        user: str = "",
    ) -> dict:
        """Validate and begin. The work continues in the background; poll ``snapshot``."""
        if not plan.automatic:
            return {"success": False, "error_code": f"update_{plan.reason or 'not_possible'}"}
        if parse_version(target) is None or not is_newer(target, VERSION):
            return {"success": False, "error_code": "update_no_update"}
        with self._lock:
            if self.busy():
                return {"success": False, "error_code": "update_busy"}
            self.state = {"phase": "backing_up", "target": target, "from": VERSION}
        logger.warning(
            "Update to %s requested from the web UI by %s (%s)", target, user, plan.mechanism
        )
        self._task = asyncio.create_task(
            self._run(plan, target, db_path, data_dir, config_path, restart, exit_app, watchtower)
        )
        return {"success": True, **self.snapshot()}

    async def _run(self, plan, target, db_path, data_dir, config_path, restart, exit_app,
                   watchtower) -> None:
        try:
            folder = await asyncio.to_thread(back_up, db_path, data_dir, config_path, target)
            self._set(phase="installing", backup=str(folder))
        except Exception as exc:  # noqa: BLE001 — nothing changed yet, so stop here
            logger.warning("The pre-update backup failed: %s", exc)
            self._set(phase="failed", error_code="update_backup_failed")
            return

        if plan.mechanism == "watchtower":
            assert watchtower is not None
            error = await asyncio.to_thread(_post_watchtower, *watchtower)
            if error:
                self._set(phase="failed", error_code=f"update_{error}")
            else:
                self._set(phase="restarting", restart="container")
            return

        if plan.deferred:
            self._spawn_helper(plan, target, data_dir)
            self._set(phase="restarting", restart="manual")
            self._later(exit_app)
            return

        output = b""
        try:
            proc = await asyncio.create_subprocess_exec(
                *plan.argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), _STEP_TIMEOUT)
            output = out or b""
        except asyncio.TimeoutError:
            proc.kill()
            self._set(phase="failed", error_code="update_timeout", output=_tail(output))
            return
        except OSError as exc:
            self._set(phase="failed", error_code="update_failed", output=str(exc))
            return
        if proc.returncode != 0:
            logger.warning("The update install failed (exit %s)", proc.returncode)
            self._set(phase="failed", error_code="update_failed", output=_tail(output))
            return
        installed = await _installed_version()
        if installed is None or installed.lstrip("v") != target.lstrip("v"):
            self._set(phase="failed", error_code="update_not_installed", output=_tail(output))
            return
        logger.warning("IPMIDeck %s installed; restarting", target)
        if restart is None:
            self._set(phase="restart_required", output=_tail(output))
            return
        self._set(phase="restarting", restart="automatic")
        self._later(restart)

    def _later(self, action: Callable[[], None] | None) -> None:
        if action is None:
            return
        asyncio.get_running_loop().call_later(_RESTART_DELAY, action)

    def _spawn_helper(self, plan: UpdatePlan, target: str, data_dir: Path) -> None:
        helper = data_dir / "update-helper.py"
        helper.write_text(_HELPER, encoding="utf-8")
        args = json.dumps(
            {
                "pid": os.getpid(),
                "argv": list(plan.argv),
                "target": target,
                "log": str(data_dir / "update.log"),
            }
        )
        detached = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(  # noqa: S603 — fixed argv, no shell
            [sys.executable, "-I", str(helper), args],
            creationflags=detached,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


async def _installed_version() -> str | None:
    """The version a fresh interpreter now imports, which is what a restart will run."""
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "from importlib.metadata import version; print(version('ipmideck'))",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), 60)
    except (OSError, asyncio.TimeoutError):
        return None
    text = (out or b"").decode("utf-8", errors="replace").strip()
    return text or None


installer = UpdateInstaller()
