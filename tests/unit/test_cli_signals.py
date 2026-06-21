"""CLI signal-handling tests — clean Ctrl+C / SIGTERM shutdown (04.1-04 gap-closure r9).

Locks the r9 fix for the UGLY shutdown traceback on Ctrl+C (Windows):

  1. `_NoSignalServer` neutralizes uvicorn's signal capture on BOTH layers — the legacy
     `install_signal_handlers()` no-op AND `capture_signals()` (the method this uvicorn version
     actually uses). uvicorn 0.42's `capture_signals()` saves the current SIGINT/SIGTERM handlers,
     installs its own `handle_exit`, then on exit RESTORES them and RE-RAISES the captured signal via
     `signal.raise_signal()`. That re-raise landed on cli()'s `_emergency_shutdown` → `sys.exit(0)`,
     dumping a `SystemExit: 0` + `asyncio.CancelledError` traceback. Neutralising `capture_signals`
     to a plain yield means uvicorn never touches the OS signal handlers — cli() owns them.

  2. The graceful signal handler (`_make_graceful_signal_handler`) flips `server.should_exit = True`
     when a live server is present in `server_box` (→ uvicorn exits its serve loop → FastAPI lifespan
     shutdown runs → fans restored), and only `sys.exit(0)`s when NO server exists yet (pre-serve
     Ctrl+C). This replaces the Windows-broken `loop.add_signal_handler` repoint (unsupported on the
     ProactorEventLoop) with `signal.signal`, which works on BOTH Windows and POSIX.

No real server is started and no real signal is raised — these are pure unit assertions on the
neutralisation + the handler's branch logic. The real Ctrl+C teardown is validated in host UAT.
"""

from __future__ import annotations

import contextlib
import signal

import pytest

import backend.main as main


# --- _NoSignalServer neutralisation --------------------------------------------------------------


def test_no_signal_server_install_signal_handlers_is_noop():
    """install_signal_handlers() is a no-op: it returns None and installs nothing.

    Snapshot the SIGINT handler, call the override, assert it is unchanged (the override must not
    install/replace anything — cli() owns SIGINT/SIGTERM)."""
    before = signal.getsignal(signal.SIGINT)
    srv = object.__new__(main._NoSignalServer)  # no __init__ (avoids needing a uvicorn.Config)
    assert main._NoSignalServer.install_signal_handlers(srv) is None
    assert signal.getsignal(signal.SIGINT) is before


def test_no_signal_server_capture_signals_does_not_touch_handlers():
    """capture_signals() is a context manager that yields and NEVER alters the SIGINT/SIGTERM handlers.

    uvicorn's default capture_signals installs handle_exit on entry, restores on exit, then RE-RAISES
    the captured signal — that re-raise was the ugly-traceback bug. Our override must do none of that:
    snapshot the handlers before / inside / after the with-block and assert they are identical (so
    nothing is installed, restored, or re-raised)."""
    srv = object.__new__(main._NoSignalServer)  # no real serve — just exercise the contextmanager

    cm = main._NoSignalServer.capture_signals(srv)
    assert isinstance(cm, contextlib._GeneratorContextManager)

    int_before = signal.getsignal(signal.SIGINT)
    term_before = signal.getsignal(signal.SIGTERM)
    with cm:
        # INSIDE the block the handlers must be untouched (uvicorn would have installed handle_exit).
        assert signal.getsignal(signal.SIGINT) is int_before
        assert signal.getsignal(signal.SIGTERM) is term_before
    # AFTER the block: still untouched, and crucially NO signal was re-raised (no exception escaped).
    assert signal.getsignal(signal.SIGINT) is int_before
    assert signal.getsignal(signal.SIGTERM) is term_before


# --- graceful signal handler (cross-platform should_exit flip) -----------------------------------


class _StubServer:
    """Minimal stand-in for the live uvicorn server: only `should_exit` matters to the handler."""

    def __init__(self) -> None:
        self.should_exit = False


def test_graceful_signal_flips_should_exit_when_serving():
    """With a live server in the box, the handler flips should_exit and does NOT sys.exit.

    This is the graceful path: uvicorn exits its serve loop → FastAPI lifespan shutdown runs (fans
    restored) → asyncio.run returns → clean process exit. No SystemExit, no re-raise."""
    srv = _StubServer()
    server_box: list = [srv]
    handler = main._make_graceful_signal_handler(server_box)

    # Must NOT raise SystemExit when a server is present.
    handler(signal.SIGINT, None)

    assert srv.should_exit is True


def test_graceful_signal_sys_exits_when_no_server_yet():
    """Pre-serve (server_box[0] is None): nothing to flip, so the handler falls back to sys.exit(0).

    This preserves FIX-03 layer 2 — a Ctrl+C during early boot (before the server object exists)
    still exits cleanly instead of hanging."""
    server_box: list = [None]
    handler = main._make_graceful_signal_handler(server_box)

    with pytest.raises(SystemExit) as exc:
        handler(signal.SIGTERM, None)
    assert exc.value.code == 0


def test_graceful_signal_uses_signal_signal_not_add_signal_handler():
    """The fix must install via signal.signal (cross-platform), NOT a loop.add_signal_handler CALL.

    add_signal_handler is unsupported on the Windows ProactorEventLoop (the original bug — the
    repoint silently failed and the handler stayed _emergency_shutdown). Source-level guard: cli()
    (which includes the nested _serve_forever) must contain NO `.add_signal_handler(` invocation and
    MUST install the handler via `signal.signal(`. We check for the call syntax (an open paren), not
    the bare token, because the docstrings/comments legitimately MENTION add_signal_handler to
    explain why it is avoided."""
    import inspect

    src = inspect.getsource(main.cli)
    assert ".add_signal_handler(" not in src  # no functional repoint call anywhere in cli()
    assert "signal.signal(" in src  # the cross-platform install IS used
