"""Installing a newer IPMIDeck from the web UI.

What is pinned: which installs can update themselves and which only get a command, that the data
is copied aside before anything changes, that success means the new version is really the one a
fresh interpreter imports, and that the endpoint refuses in demo mode, without a login, and with
nothing newer to install.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import stat
from contextlib import closing
import sys
from pathlib import Path

import pytest

import backend.main as bm
from backend.core import update_install as ui
from backend.core.update_install import UpdateInstaller, UpdatePlan, plan_for

NEWER = "99.0.0"


# === Which installs can do it ===


def _flavor(name):
    return lambda: name


def test_nothing_newer_means_nothing_to_plan():
    assert plan_for("pip", None).reason == "no_update"


def test_docker_without_watchtower_gets_the_command():
    plan = plan_for("docker", NEWER)
    assert (plan.automatic, plan.reason) == (False, "docker")
    assert plan.command == "docker compose pull && docker compose up -d"


def test_docker_with_watchtower_is_automatic():
    plan = plan_for("docker", NEWER, watchtower=True)
    assert (plan.automatic, plan.mechanism, plan.restart) == (True, "watchtower", "container")


@pytest.mark.parametrize(
    ("method", "flavor", "reason"),
    [
        ("git", "venv", "git"),
        ("unknown", "venv", "unknown"),
        ("pip", "editable", "editable"),
        ("pip", "managed", "system_python"),
    ],
)
def test_installs_that_only_get_a_command(method, flavor, reason):
    plan = plan_for(method, NEWER, flavor=_flavor(flavor))
    assert (plan.automatic, plan.reason) == (False, reason)


def test_a_venv_upgrades_with_its_own_pip_and_restarts(monkeypatch):
    monkeypatch.setattr(ui, "_pip_available", lambda: True)
    plan = plan_for("pip", NEWER, can_restart=True, platform="linux", flavor=_flavor("venv"))
    assert plan.automatic and plan.mechanism == "pip" and plan.restart == "automatic"
    assert plan.argv == (sys.executable, "-m", "pip", "install", "--upgrade", f"ipmideck=={NEWER}")


def test_a_user_install_stays_a_user_install(monkeypatch):
    monkeypatch.setattr(ui, "_pip_available", lambda: True)
    plan = plan_for("pip", NEWER, platform="linux", flavor=_flavor("user"))
    assert "--user" in plan.argv
    assert plan.restart == "manual"  # not started by the ipmideck command: nothing to restart it


def test_a_uv_tool_goes_through_uv(monkeypatch):
    monkeypatch.setattr(ui.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    plan = plan_for("pip", NEWER, platform="linux", flavor=_flavor("uv"))
    assert plan.argv == ("/usr/bin/uv", "tool", "install", "--force", f"ipmideck=={NEWER}")


def test_a_uv_tool_without_uv_on_path_gets_the_command(monkeypatch):
    monkeypatch.setattr(ui.shutil, "which", lambda name: None)
    plan = plan_for("pip", NEWER, platform="linux", flavor=_flavor("uv"))
    assert (plan.automatic, plan.reason) == (False, "tool_missing")


def test_pipx_without_pip_goes_through_pipx(monkeypatch):
    monkeypatch.setattr(ui, "_pip_available", lambda: False)
    monkeypatch.setattr(ui.shutil, "which", lambda name: "/usr/bin/pipx" if name == "pipx" else None)
    plan = plan_for("pip", NEWER, platform="linux", flavor=_flavor("pipx"))
    assert plan.mechanism == "pipx"
    assert plan.argv == ("/usr/bin/pipx", "install", "--force", f"ipmideck=={NEWER}")


def test_no_pip_and_no_tool_gets_the_command(monkeypatch):
    monkeypatch.setattr(ui, "_pip_available", lambda: False)
    plan = plan_for("pip", NEWER, platform="linux", flavor=_flavor("venv"))
    assert (plan.automatic, plan.reason) == (False, "pip_missing")


def test_windows_installs_after_the_app_exits(monkeypatch):
    monkeypatch.setattr(ui, "_pip_available", lambda: True)
    plan = plan_for("pip", NEWER, can_exit=True, platform="win32", flavor=_flavor("venv"))
    assert plan.automatic and plan.deferred and plan.restart == "manual"
    blocked = plan_for("pip", NEWER, platform="win32", flavor=_flavor("venv"))
    assert (blocked.automatic, blocked.reason) == (False, "manual_only")


def test_the_flavor_reads_the_tool_markers(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "_editable", lambda: False)
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    (tmp_path / "uv-receipt.toml").write_text("", encoding="utf-8")
    assert ui.python_flavor() == "uv"
    (tmp_path / "uv-receipt.toml").unlink()
    (tmp_path / "pipx_metadata.json").write_text("{}", encoding="utf-8")
    assert ui.python_flavor() == "pipx"


def test_an_editable_install_is_never_upgraded_from_the_index(monkeypatch):
    monkeypatch.setattr(ui, "_editable", lambda: True)
    assert ui.python_flavor() == "editable"


# === The copy made first ===


def test_the_backup_copies_the_database_key_and_config(tmp_path):
    db_path = tmp_path / "ipmideck.db"
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("create table t (v text)")
        conn.execute("insert into t values ('kept')")
    (tmp_path / "encryption.key").write_bytes(b"k" * 32)
    config = tmp_path / "config.yaml"
    config.write_text("server: {}\n", encoding="utf-8")

    folder = ui.back_up(db_path, tmp_path, config, NEWER)

    assert folder.parent == tmp_path / "backups"
    assert {p.name for p in folder.iterdir()} == {"ipmideck.db", "encryption.key", "config.yaml"}
    with closing(sqlite3.connect(folder / "ipmideck.db")) as copy:
        assert copy.execute("select v from t").fetchone() == ("kept",)


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits; Windows takes the ACL path instead")
def test_the_backup_folder_is_owner_only_and_still_enterable(tmp_path):
    """0600 on a folder drops the execute bit, and then not even its owner can write in it: the
    backup failed with "unable to open database file" in the Docker image, which runs as an
    unprivileged user. The folder is 0700, the copies inside 0600."""
    db_path = tmp_path / "ipmideck.db"
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("create table t (v text)")
    (tmp_path / "encryption.key").write_bytes(b"k" * 32)

    folder = ui.back_up(db_path, tmp_path, None, NEWER)

    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert {stat.S_IMODE(p.stat().st_mode) for p in folder.iterdir()} == {0o600}


# === Only the most recent copies are kept ===


def _old_backups(tmp_path, stamps):
    """Earlier pre-update folders, one per stamp, each holding a stand-in key."""
    folders = []
    for i, stamp in enumerate(stamps):
        folder = tmp_path / "backups" / f"pre-update-2.0.0-to-2.0.{i}-{stamp}"
        folder.mkdir(parents=True)
        (folder / "encryption.key").write_bytes(b"k" * 32)
        folders.append(folder)
    return folders


_FIVE = [f"2020010{d}T000000Z" for d in range(1, 6)]


def test_only_the_three_most_recent_backups_are_kept(tmp_path):
    old = _old_backups(tmp_path, _FIVE)
    folder = ui.back_up(tmp_path / "ipmideck.db", tmp_path, None, NEWER)
    left = set((tmp_path / "backups").iterdir())
    assert left == {folder, old[3], old[4]}


def test_the_backups_are_ordered_by_the_stamp_in_their_name_not_mtime(tmp_path):
    old = _old_backups(tmp_path, _FIVE)
    # The oldest stamp gets the newest mtime: a restore or a copy rewrites mtimes.
    for age, folder in enumerate(old):
        stamp_time = 2_000_000_000 - age * 1000
        os.utime(folder, (stamp_time, stamp_time))
    folder = ui.back_up(tmp_path / "ipmideck.db", tmp_path, None, NEWER)
    assert set((tmp_path / "backups").iterdir()) == {folder, old[3], old[4]}


def test_anything_else_in_the_backups_folder_is_left_alone(tmp_path):
    _old_backups(tmp_path, _FIVE)
    backups = tmp_path / "backups"
    foreign = [
        backups / "manual-copy",
        backups / "pre-update-1.0.0-to-2.0.0-notastamp",
    ]
    for folder in foreign:
        folder.mkdir()
    files = [
        backups / "pre-update-notes.txt",
        backups / "pre-update-1.0.0-to-1.0.1-20190101T000000Z",
    ]
    for item in files:
        item.write_text("kept", encoding="utf-8")
    ui.back_up(tmp_path / "ipmideck.db", tmp_path, None, NEWER)
    for item in foreign + files:
        assert item.exists()


def test_a_backup_that_cannot_be_removed_never_fails_the_update(tmp_path, monkeypatch, caplog):
    _old_backups(tmp_path, _FIVE)
    (tmp_path / "encryption.key").write_bytes(b"k" * 32)

    def refuse(path, *args, **kwargs):
        raise OSError("in use")

    monkeypatch.setattr(ui.shutil, "rmtree", refuse)
    with caplog.at_level(logging.WARNING, logger="ipmideck.updates"):
        folder = ui.back_up(tmp_path / "ipmideck.db", tmp_path, None, NEWER)
    assert (folder / "encryption.key").read_bytes() == b"k" * 32
    assert len(list((tmp_path / "backups").iterdir())) == 6
    assert any("Could not remove the old pre-update backup" in r.message for r in caplog.records)


def test_the_backup_just_made_is_kept_even_when_older_ones_look_newer(tmp_path):
    # A clock that went backwards: the earlier folders carry later stamps.
    later = _old_backups(tmp_path, [f"2099010{d}T000000Z" for d in range(1, 5)])
    folder = ui.back_up(tmp_path / "ipmideck.db", tmp_path, None, NEWER)
    assert set((tmp_path / "backups").iterdir()) == {folder, later[2], later[3]}


# === Running it ===


class _Proc:
    def __init__(self, code: int, out: bytes = b""):
        self.returncode = code
        self._out = out

    async def communicate(self):
        return self._out, None

    def kill(self):
        pass


def _fake_exec(monkeypatch, install_code=0, reported=NEWER):
    calls = []

    async def fake(*argv, **kwargs):
        calls.append(argv)
        if "-c" in argv:  # the version check in a fresh interpreter
            return _Proc(0, f"{reported}\n".encode())
        return _Proc(install_code, b"Successfully installed ipmideck\n")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake)
    return calls


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "_RESTART_DELAY", 0)
    monkeypatch.setattr(ui, "back_up", lambda *a: tmp_path / "backups" / "copy")
    return {"db_path": tmp_path / "ipmideck.db", "data_dir": tmp_path, "config_path": None}


def _pip_plan(**fields):
    base = {"automatic": True, "mechanism": "pip", "restart": "automatic",
            "argv": ("python", "-m", "pip", "install", "--upgrade", f"ipmideck=={NEWER}")}
    return UpdatePlan(**{**base, **fields})


async def _finish(installer: UpdateInstaller):
    await installer._task
    await asyncio.sleep(0.01)  # let a scheduled restart run


async def test_an_install_that_works_restarts_into_the_new_version(monkeypatch, paths):
    calls = _fake_exec(monkeypatch)
    restarted = []
    installer = UpdateInstaller()
    answer = await installer.start(
        plan=_pip_plan(), target=NEWER, restart=lambda: restarted.append(True), exit_app=None,
        **paths,
    )
    assert answer["success"] is True
    await _finish(installer)
    assert installer.state["phase"] == "restarting"
    assert restarted == [True]
    assert calls[0][-1] == f"ipmideck=={NEWER}"


async def test_a_failed_install_does_not_restart(monkeypatch, paths):
    _fake_exec(monkeypatch, install_code=1)
    restarted = []
    installer = UpdateInstaller()
    await installer.start(
        plan=_pip_plan(), target=NEWER, restart=lambda: restarted.append(True), exit_app=None,
        **paths,
    )
    await _finish(installer)
    assert installer.state["phase"] == "failed"
    assert installer.state["error_code"] == "update_failed"
    assert "Successfully installed" in installer.state["output"]
    assert restarted == []


async def test_success_means_the_new_version_is_what_python_imports(monkeypatch, paths):
    _fake_exec(monkeypatch, reported="1.0.0")
    installer = UpdateInstaller()
    await installer.start(plan=_pip_plan(), target=NEWER, restart=None, exit_app=None, **paths)
    await _finish(installer)
    assert installer.state["error_code"] == "update_not_installed"


async def test_without_a_way_to_restart_it_says_so(monkeypatch, paths):
    _fake_exec(monkeypatch)
    installer = UpdateInstaller()
    await installer.start(plan=_pip_plan(), target=NEWER, restart=None, exit_app=None, **paths)
    await _finish(installer)
    assert installer.state["phase"] == "restart_required"


async def test_a_failed_backup_stops_before_anything_changes(monkeypatch, tmp_path):
    calls = _fake_exec(monkeypatch)

    def broken(*args):
        raise OSError("disk full")

    monkeypatch.setattr(ui, "back_up", broken)
    installer = UpdateInstaller()
    await installer.start(
        plan=_pip_plan(), target=NEWER, restart=None, exit_app=None,
        db_path=tmp_path / "x.db", data_dir=tmp_path, config_path=None,
    )
    await _finish(installer)
    assert installer.state["error_code"] == "update_backup_failed"
    assert calls == []


async def test_windows_hands_over_to_a_helper_and_exits(monkeypatch, paths):
    spawned = []
    monkeypatch.setattr(ui.subprocess, "Popen", lambda argv, **kw: spawned.append(argv))
    exited = []
    installer = UpdateInstaller()
    await installer.start(
        plan=_pip_plan(deferred=True, restart="manual"), target=NEWER, restart=None,
        exit_app=lambda: exited.append(True), **paths,
    )
    await _finish(installer)
    assert installer.state["phase"] == "restarting"
    assert exited == [True]
    assert spawned[0][1] == "-I"
    assert Path(spawned[0][2]).read_text(encoding="utf-8").startswith("\n\"\"\"Waits for IPMIDeck")


async def test_watchtower_is_asked_to_update(monkeypatch, paths):
    asked = []
    monkeypatch.setattr(ui, "_post_watchtower", lambda url, token: asked.append((url, token)))
    installer = UpdateInstaller()
    await installer.start(
        plan=UpdatePlan(True, "watchtower", restart="container"), target=NEWER, restart=None,
        exit_app=None, watchtower=("http://192.0.2.5:8080", "secret"), **paths,
    )
    await _finish(installer)
    assert asked == [("http://192.0.2.5:8080", "secret")]
    assert installer.state["phase"] == "restarting"
    # The page waits for the new container rather than for this process to restart itself.
    assert installer.state["restart"] == "container"


async def test_a_refusing_watchtower_is_reported(monkeypatch, paths):
    monkeypatch.setattr(ui, "_post_watchtower", lambda url, token: "watchtower_unauthorized")
    installer = UpdateInstaller()
    await installer.start(
        plan=UpdatePlan(True, "watchtower", restart="container"), target=NEWER, restart=None,
        exit_app=None, watchtower=("http://192.0.2.5:8080", "wrong"), **paths,
    )
    await _finish(installer)
    assert installer.state["error_code"] == "update_watchtower_unauthorized"


async def test_refusals_before_anything_starts(paths):
    installer = UpdateInstaller()
    refused = await installer.start(
        plan=UpdatePlan(False, reason="git"), target=NEWER, restart=None, exit_app=None, **paths
    )
    assert refused["error_code"] == "update_git"
    older = await installer.start(
        plan=_pip_plan(), target="0.0.1", restart=None, exit_app=None, **paths
    )
    assert older["error_code"] == "update_no_update"
    installer.state = {"phase": "installing"}
    busy = await installer.start(plan=_pip_plan(), target=NEWER, restart=None, exit_app=None,
                                 **paths)
    assert busy["error_code"] == "update_busy"


def test_watchtower_errors_are_named(monkeypatch):
    import urllib.error

    def refused(*a, **k):
        raise urllib.error.URLError(ConnectionRefusedError())

    monkeypatch.setattr(ui.urllib.request, "urlopen", refused)
    assert ui._post_watchtower("http://192.0.2.5:8080", "t") == "watchtower_unreachable"

    def unauthorized(*a, **k):
        raise urllib.error.HTTPError("u", 401, "no", {}, None)

    monkeypatch.setattr(ui.urllib.request, "urlopen", unauthorized)
    assert ui._post_watchtower("http://192.0.2.5:8080", "t") == "watchtower_unauthorized"

    def cut_short(*a, **k):
        raise TimeoutError()

    monkeypatch.setattr(ui.urllib.request, "urlopen", cut_short)
    assert ui._post_watchtower("http://192.0.2.5:8080", "t") is None


# === The routes ===


def test_the_install_route_refuses_in_demo_mode(client):
    assert client.post("/api/updates/install").json() == {
        "success": False,
        "error_code": "update_demo",
    }


def test_the_install_route_refuses_without_a_login(client, monkeypatch):
    monkeypatch.setattr(bm.config, "demo", False)
    assert client.post("/api/updates/install").json()["error_code"] == "update_needs_login"


async def test_the_install_route_refuses_with_nothing_newer(monkeypatch):
    from backend.api import update_routes
    from backend.core.update_service import UpdateStatus

    monkeypatch.setattr(bm.config, "demo", False)

    async def on():
        return True

    async def nothing():
        return UpdateStatus()

    class Service:
        cached_status = staticmethod(nothing)

    monkeypatch.setattr(bm.auth, "is_auth_enabled", on)
    monkeypatch.setattr(bm, "update_service", Service)
    result = await update_routes.install_update(user="operator")
    assert result["error_code"] == "update_no_update"


def test_the_state_describes_how_an_update_would_install(client, monkeypatch):
    from backend.core.update_service import UpdateStatus

    async def found():
        return UpdateStatus(latest_version=NEWER, update_available=True, install_method="docker",
                            notes="### Fixed\n\n- **A fix.**")

    monkeypatch.setattr(bm.update_service, "cached_status", found)
    body = client.get("/api/updates/state").json()
    assert body["upgrade"]["reason"] == "docker"
    assert body["upgrade"]["command"].startswith("docker compose pull")
    assert body["notes"].startswith("### Fixed")


def test_the_install_state_starts_idle(client):
    assert client.get("/api/updates/install").json()["phase"] in ("idle", "failed", "restarting",
                                                                  "restart_required")


def test_watchtower_settings_come_from_the_environment(monkeypatch):
    from backend.core.config import AppConfig, _apply_env_overrides

    monkeypatch.setenv("IPMIDECK_UPDATES_WATCHTOWER_URL", "http://192.0.2.5:8080")
    monkeypatch.setenv("IPMIDECK_UPDATES_WATCHTOWER_TOKEN", "tok")
    config = AppConfig()
    _apply_env_overrides(config)
    assert config.updates.watchtower_url == "http://192.0.2.5:8080"
    assert config.updates.watchtower_token == "tok"
