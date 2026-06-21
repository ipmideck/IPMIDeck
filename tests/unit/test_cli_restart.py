"""CLI restart tests (04.1-04 gap-closure r10 + r11 platform split).

r10 replaced the BROKEN in-process re-serve (key 'r') with a graceful shutdown + console teardown
+ process re-exec. r11 makes that re-exec PLATFORM-AWARE because Windows has no true exec():

  POSIX (sys.platform != "win32"):
    os.execv replaces the process IN PLACE (same PID, controlling terminal inherited) — reliable.
    Restart re-execs `python -m backend.main` with --host/--port STRIPPED so the re-read config.yaml
    (where change-bind persisted the new bind) supplies the host/port. OSError → subprocess fallback.

  Windows (sys.platform == "win32"):
    os.execv is EMULATED as spawn-child + exit-parent. For an INTERACTIVE console app the console /
    stdin handoff breaks (host UAT: pressing 'r' kept the OLD bind, then froze — r/ESC/Ctrl+C dead).
    So on Windows we do NOT execv and do NOT spawn: we print a clear "run `ipmideck start` again to
    restart" message and exit cleanly, letting the user's proven manual shell relaunch re-read config.

The platform branch is factored into the module-level `_do_restart(...)` helper so it is unit-testable
WITHOUT serving a real server, calling a real os.execv, or spawning a real process: execv/popen are
INJECTED and the platform is passed explicitly. The graceful-shutdown ordering (serve() before the
restart action) and the console teardown (stop/join before the restart action) are asserted at source
level against cli(). The real restart is validated in host UAT.
"""

from __future__ import annotations

import sys

import backend.main as main


# --- _reexec_args: strip --host/--port (and their values) so the re-exec uses persisted config -----


def test_reexec_args_strips_space_separated_host_and_port():
    """`--host X` / `--port Y` and their value tokens are removed so config.yaml supplies the bind."""
    argv = ["start", "--host", "0.0.0.0", "--port", "8080"]
    assert main._reexec_args(argv) == ["start"]


def test_reexec_args_strips_combined_equals_forms():
    """The `--host=X` / `--port=Y` combined forms are removed too (no trailing value token to drop)."""
    argv = ["start", "--host=127.0.0.1", "--port=9000", "--demo"]
    assert main._reexec_args(argv) == ["start", "--demo"]


def test_reexec_args_keeps_other_flags_and_values():
    """Non-bind args survive verbatim: `start`, `--demo`, `--config <path>`, `--reload`."""
    argv = ["start", "--demo", "--config", "/etc/ipmideck/config.yaml", "--reload"]
    assert main._reexec_args(argv) == [
        "start",
        "--demo",
        "--config",
        "/etc/ipmideck/config.yaml",
        "--reload",
    ]


def test_reexec_args_does_not_strip_config_value_that_follows_port():
    """A value token after a stripped --port must drop ONLY the port's value, not a following arg.

    Regression guard: dropping `--port 8080` must consume exactly one value (8080) and NOT also eat
    the next unrelated flag/value (`--config path`)."""
    argv = ["--port", "8080", "--config", "/data/config.yaml", "start"]
    assert main._reexec_args(argv) == ["--config", "/data/config.yaml", "start"]


def test_reexec_args_strips_p_alias_space_and_equals():
    """The `-p` short alias (space and =form) is stripped too (defensive — if it ever aliases --port)."""
    assert main._reexec_args(["start", "-p", "8080"]) == ["start"]
    assert main._reexec_args(["start", "-p=8080", "--demo"]) == ["start", "--demo"]


def test_reexec_args_empty_and_no_bind_flags_passthrough():
    """No bind flags → args pass through unchanged; empty argv → empty list."""
    assert main._reexec_args([]) == []
    assert main._reexec_args(["start", "--demo"]) == ["start", "--demo"]


def test_reexec_args_returns_new_list_does_not_mutate_input():
    """_reexec_args is pure: it returns a NEW list and does not mutate the caller's argv."""
    argv = ["start", "--host", "0.0.0.0", "--port", "8080"]
    snapshot = list(argv)
    out = main._reexec_args(argv)
    assert argv == snapshot  # input untouched
    assert out is not argv


# --- entry-point guard: `python -m backend.main` must run cli() -----------------------------------


def test_main_module_has_dunder_main_guard():
    """backend/main.py has `if __name__ == \"__main__\": cli()` so `python -m backend.main` serves.

    The re-exec runs `python -m backend.main <args>`; that only invokes cli() if the module has the
    standard __main__ guard. Source-level assertion (running the module would start a real server)."""
    import inspect

    src = inspect.getsource(main)
    assert 'if __name__ == "__main__":' in src
    # cli() must be the call under the guard (allow whitespace/newlines between).
    guard_idx = src.index('if __name__ == "__main__":')
    assert "cli()" in src[guard_idx:], "the __main__ guard must call cli()"


# --- _do_restart: platform split (POSIX re-exec vs Windows clean-exit message) ---------------------


def test_do_restart_posix_calls_execv_with_stripped_args(monkeypatch):
    """POSIX path: _do_restart calls os.execv with `python -m backend.main` + _reexec_args(args).

    execv is INJECTED (mock) so nothing is actually exec'd. We assert the exact argv: the interpreter,
    the `-m backend.main` re-launch, and the bind-stripped tail (so config.yaml supplies the bind)."""
    calls: dict = {}

    def fake_execv(path, argv):
        calls["path"] = path
        calls["argv"] = argv

    def fake_popen(argv, **kwargs):  # must NOT be used on the happy POSIX path
        calls["popen"] = argv

    main._do_restart(
        platform="linux",
        argv_tail=["start", "--host", "0.0.0.0", "--port", "8080"],
        execv=fake_execv,
        popen=fake_popen,
    )

    assert calls["path"] == sys.executable
    assert calls["argv"] == [
        sys.executable,
        "-m",
        "backend.main",
        "start",  # --host/--port stripped by _reexec_args
    ]
    assert "popen" not in calls, "the happy POSIX path must not spawn a subprocess"


def test_do_restart_posix_falls_back_to_subprocess_on_execv_oserror(monkeypatch):
    """POSIX path: if injected execv raises OSError, _do_restart spawns via popen then exits(0).

    execv can fail (rare: bad interpreter path). The fallback must spawn a replacement so 'r' still
    restarts, then exit the original. SystemExit(0) is expected and asserted."""
    calls: dict = {}

    def fake_execv(path, argv):
        raise OSError("simulated execv failure")

    def fake_popen(argv, **kwargs):
        calls["popen"] = argv

    import pytest

    with pytest.raises(SystemExit) as exc:
        main._do_restart(
            platform="linux",
            argv_tail=["start"],
            execv=fake_execv,
            popen=fake_popen,
        )
    assert exc.value.code == 0
    assert calls["popen"] == [sys.executable, "-m", "backend.main", "start"]


def test_do_restart_windows_does_not_execv_or_spawn_and_returns(capsys):
    """Windows path: _do_restart must NOT call execv and NOT spawn — it prints a relaunch hint, returns.

    Windows has no true exec(); the emulated spawn-child/exit-parent breaks the interactive console
    handoff (host UAT: child froze, old bind kept). The reliable path is the user's manual relaunch,
    so we exit cleanly with a clear message instead of exec/spawn."""
    called = {"execv": False, "popen": False}

    def fake_execv(path, argv):
        called["execv"] = True

    def fake_popen(argv, **kwargs):
        called["popen"] = True

    # Must NOT raise SystemExit — it returns so the caller's finally (teardown) runs cleanly.
    ret = main._do_restart(
        platform="win32",
        argv_tail=["start", "--host", "0.0.0.0", "--port", "8080"],
        execv=fake_execv,
        popen=fake_popen,
    )
    assert ret is None
    assert called["execv"] is False, "Windows must NOT os.execv (emulated exec breaks the console)"
    assert called["popen"] is False, "Windows must NOT spawn a subprocess"

    out = capsys.readouterr().out
    # The message must clearly tell the operator to relaunch with the product command.
    assert "ipmideck start" in out, "Windows restart must hint the manual relaunch command"
    assert main.APP_NAME in out


def test_do_restart_default_execv_and_popen_are_real_stdlib():
    """_do_restart's injected execv/popen default to the real os.execv / subprocess.Popen.

    The production call site relies on the defaults; tests inject mocks. Source-level guard that the
    defaults reference the stdlib functions (so we never accidentally default to a no-op)."""
    import inspect

    src = inspect.getsource(main._do_restart)
    assert "os.execv" in src
    assert "subprocess.Popen" in src


# --- restart block ordering in cli(): serve() + console teardown BEFORE the restart action ---------


def test_restart_block_calls_do_restart_with_platform_and_argv(monkeypatch):
    """cli()'s restart path delegates to _do_restart(...) passing the current platform + sys.argv tail.

    Source-level guard: the restart path must call _do_restart with sys.platform and sys.argv[1:] so
    the platform split (POSIX execv vs Windows clean-exit) is honored and the re-exec uses the live
    argv. (Running cli() would serve a real server — assert at source.)"""
    import inspect

    src = inspect.getsource(main.cli)
    assert "_do_restart(" in src, "the restart path must delegate to _do_restart"
    assert "sys.platform" in src, "the platform must be passed so POSIX/Windows split is honored"
    assert "sys.argv[1:]" in src, "the live argv tail must be passed to _do_restart"


def test_restart_block_tears_down_console_before_do_restart():
    """The restart path must stop the console + join the render thread BEFORE calling _do_restart.

    On Windows _do_restart prints + returns; on POSIX it execs. EITHER way the alternate screen must
    already be restored (console.stop + render_thread.join) before the restart action, or the terminal
    is left corrupted / the new process inherits a Live-owned screen. Source-level ordering guard."""
    import inspect

    src = inspect.getsource(main.cli)
    do_idx = src.index("_do_restart(")
    stop_idx = src.rindex("console.stop()", 0, do_idx)
    join_idx = src.rindex(".join(", 0, do_idx)
    assert stop_idx < do_idx, "console.stop() must run before _do_restart (restore alt screen)"
    assert join_idx < do_idx, "render_thread.join() must run before _do_restart"


def test_restart_block_no_in_process_reserve():
    """The dead in-process re-serve message must be GONE — restart is a process re-exec / clean exit.

    The old loop logged 'restarting in-process…' and re-awaited serve() in the same loop (the bug).
    That path is removed. We assert the in-process restart log line is no longer present in cli()."""
    import inspect

    src = inspect.getsource(main.cli)
    assert "restarting in-process" not in src


def test_restart_block_runs_serve_before_restart_action():
    """Graceful shutdown (fan restore in lifespan) runs inside serve() BEFORE the restart action.

    The restart must NOT skip or reorder the graceful shutdown: `await server.serve()` (which runs the
    full FastAPI lifespan including the fan-restore shutdown — FIX-03 L1) must appear before the
    _do_restart call. Source-level guard so we never regress the safety-critical fan restore."""
    import inspect

    src = inspect.getsource(main.cli)
    serve_idx = src.index("await server.serve()")
    do_idx = src.index("_do_restart(")
    assert serve_idx < do_idx, "serve() (graceful lifespan shutdown) must run before the restart"
