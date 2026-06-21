"""CLI restart-via-re-exec tests (04.1-04 gap-closure r10).

Locks the r10 fix for the BROKEN in-process restart (key 'r'):

  Pressing 'r' used to re-create a uvicorn Server and re-await server.serve() in the SAME asyncio
  loop. uvicorn 0.42's serve() is single-shot and cannot be safely re-run in the same loop → the
  rebind failed (site unreachable on BOTH old and new bind) and any exception left the loop dead
  while the non-daemon render thread kept the process alive → 'r'/'q'/Ctrl+C froze. The robust fix
  is what the operator did manually: graceful shutdown (lifespan fan-restore runs inside serve())
  → tear down the console → re-exec a FRESH process that re-reads config.yaml (the change-bind
  persisted the new bind there) and binds the new port.

These are PURE/behavioral assertions. No real server is served, no real os.execv is called, no real
process is spawned — _reexec_args is a pure function, and the re-exec ordering is asserted at source
level (the restart block must tear the console down BEFORE os.execv and use _reexec_args). The real
restart is validated in host UAT.
"""

from __future__ import annotations

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


# --- restart block ordering: console teardown BEFORE os.execv, using _reexec_args -----------------


def test_restart_block_tears_down_console_before_execv_and_uses_reexec_args():
    """The restart path must: stop the console + join the render thread BEFORE os.execv, and build
    the re-exec argv from _reexec_args (so the new process re-reads the persisted config.yaml bind).

    Source-level ordering guard (no real serve/execv): we locate the restart re-exec section in
    cli() and assert console.stop() and render_thread.join(...) appear BEFORE the os.execv call, and
    that the argv passed to execv runs `python -m backend.main` + _reexec_args(...). This keeps the
    alternate screen restored before the new process starts (otherwise the terminal is corrupted)."""
    import inspect

    src = inspect.getsource(main.cli)
    # the re-exec uses os.execv with `-m backend.main` and the stripped args from _reexec_args
    assert "os.execv(" in src, "restart must re-exec the process via os.execv"
    assert '"-m", "backend.main"' in src or "'-m', 'backend.main'" in src
    assert "_reexec_args(" in src, "the re-exec argv must be built from _reexec_args"

    execv_idx = src.index("os.execv(")
    # console teardown must come BEFORE the execv (alt screen restored first)
    stop_idx = src.rindex("console.stop()", 0, execv_idx)
    join_idx = src.rindex(".join(", 0, execv_idx)
    assert stop_idx < execv_idx, "console.stop() must run before os.execv (restore alt screen)"
    assert join_idx < execv_idx, "render_thread.join() must run before os.execv"


def test_restart_block_falls_back_to_subprocess_on_execv_oserror():
    """If os.execv raises OSError the restart falls back to subprocess.Popen + sys.exit(0).

    execv can fail (rare: bad interpreter path / platform quirk). The block must catch OSError and
    spawn a replacement via subprocess before exiting, so 'r' still restarts. Source-level guard."""
    import inspect

    src = inspect.getsource(main.cli)
    execv_idx = src.index("os.execv(")
    tail = src[execv_idx:]
    assert "except OSError" in tail, "execv failure must be caught"
    assert "subprocess.Popen(" in tail, "the fallback must spawn via subprocess.Popen"
    assert "sys.exit(0)" in tail, "after the subprocess fallback the original process must exit"


def test_restart_block_no_in_process_reserve():
    """The dead in-process re-serve message must be GONE — restart is now a process re-exec (r10).

    The old loop logged 'restarting in-process…' and re-awaited serve() in the same loop (the bug).
    That path is removed; the restart re-execs instead. We assert the in-process restart log line is
    no longer present in cli()."""
    import inspect

    src = inspect.getsource(main.cli)
    assert "restarting in-process" not in src


def test_restart_block_runs_serve_before_reexec():
    """Graceful shutdown (fan restore in lifespan) runs inside serve() BEFORE the re-exec (FIX-03 L1).

    The restart must NOT skip or reorder the graceful shutdown: `await server.serve()` (which runs
    the full FastAPI lifespan including the fan-restore shutdown) must appear before the os.execv
    re-exec. Source-level guard so we never regress the safety-critical fan restore."""
    import inspect

    src = inspect.getsource(main.cli)
    serve_idx = src.index("await server.serve()")
    execv_idx = src.index("os.execv(")
    assert serve_idx < execv_idx, "serve() (graceful lifespan shutdown) must run before re-exec"
