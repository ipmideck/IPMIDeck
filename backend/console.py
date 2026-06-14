"""Host-only interactive operator console (D-01..D-07, D-11, D-13, D-14, D-15a/b/d, D-17, D-19, D-23, D-24).

This module is the high-risk rich/keypress/port-guard surface, isolated behind import-safety so
the Linux Docker container is NEVER broken (D-22/D-23). It is import-safe on Linux even though the
interactive loop never runs there: rich, pyfiglet, msvcrt, termios and tty are imported LAZILY
inside functions/methods, never at module level. Only stdlib that exists on every platform is
imported at the top.

Callback-driven by design: ConsoleUI takes plain callables (get_url / get_servers / on_exit /
on_restart / on_set_verbosity / on_change_bind) so it never imports backend.main — Plan 04 wires
the real implementations in cli().

SCROLLBACK TRADEOFF (RESEARCH Pitfall 1 — accepted): rich has NO native scrolling. The pinned-top
header + below-it scrolling-log layout (D-01) is achieved with rich Live(screen=True) + Layout +
a collections.deque(maxlen=N) tail. The body shows only the last N lines; older lines fall out of
the deque and cannot be mouse-scrolled back. Logs STILL flow to the normal log file/stderr for the
full history once Live exits — the deque is only the on-screen tail. This bounded-scrollback cost
is the deliberate tradeoff for a true top-pinned header in pure rich (Textual would be needed for
real scrollback and is out of scope).

HANDLER ROUTING (RESEARCH Pitfall 6): while Live owns the screen, logging is routed through a
DequeLogHandler attached to the root logger so log records render in the body region instead of
fighting the Live render. run() installs the handler and stop()/run()'s finally removes it, so the
normal stdout/stderr logging is restored on exit.
"""

from __future__ import annotations

import logging
import socket
import sys
import threading
from collections import deque
from datetime import datetime, timezone  # noqa: F401  (imported for handler/UI timestamp use)


def port_in_use(host: str, port: int) -> bool:
    """Return True if ``port`` is already bound/listening on ``host`` (D-17).

    Deliberately does NOT set SO_REUSEADDR (RESEARCH Pitfall 4): SO_REUSEADDR would let the probe
    re-bind over an already-listening socket, producing a FALSE negative and letting a second
    backend start and fight over the same BMC. A plain bind() raises OSError (EADDRINUSE /
    WinError 10048) when the port is taken — that is the "already running" signal.

    "0.0.0.0"/"::"/"" wildcard binds are probed against 127.0.0.1 so the check is meaningful.
    """
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((probe_host, port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def read_key() -> str | None:
    """Blocking read of ONE keypress, platform-guarded (D-23). Caller MUST gate on isatty() first (D-24).

    The keypress backend is imported INSIDE this function so the module stays import-safe on Linux
    (an unconditional module-level ``import msvcrt`` would crash the Linux container at import).
    Returns the character read, or None if no keypress backend is available (e.g. a stripped POSIX
    image without termios).
    """
    if sys.platform == "win32":
        import msvcrt  # guarded: Windows-only (D-23)

        return msvcrt.getwch()  # getwch = unicode, no echo
    else:
        try:
            import termios
            import tty
        except ImportError:
            return None
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)  # cbreak: char-at-a-time, Ctrl+C still delivered
            return sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def is_interactive() -> bool:
    """True only when BOTH stdin and stdout are real TTYs (D-24).

    Gates the interactive loop so Docker / systemd / piped-stdout degrade to banner-once + plain
    logs (D-07) and never busy-spin on an EOF-returning non-TTY stdin.
    """
    return sys.stdin.isatty() and sys.stdout.isatty()


def start_key_listener(
    loop, dispatch, stop_event: threading.Event | None = None
) -> threading.Thread:
    """Daemon thread that reads keypresses and hands each to ``dispatch`` on the event loop thread.

    Each key is delivered via ``loop.call_soon_threadsafe(dispatch, key)`` so dispatch runs on the
    loop thread (no cross-thread state races). If a ``stop_event`` is supplied the loop checks it
    each iteration and returns when set, so Plan 04 can tear the listener down on exit/restart.
    """

    def _loop() -> None:
        while True:
            if stop_event is not None and stop_event.is_set():
                return
            try:
                k = read_key()
            except Exception:
                return
            if k is None:
                return
            if stop_event is not None and stop_event.is_set():
                return
            loop.call_soon_threadsafe(dispatch, k)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return t


class DequeLogHandler(logging.Handler):
    """A logging.Handler that appends each formatted record to a bounded deque (D-01/D-25).

    This is the on-screen log-tail feed for ConsoleUI: while the rich Live render owns the screen,
    log records land in the deque (rendered into the body region) instead of writing to stdout and
    corrupting the Live frame (RESEARCH Pitfall 6). The deque's ``maxlen`` bounds the on-screen
    scrollback (accepted tradeoff — see module docstring); the full history still goes to the
    normal log file/stderr handlers once Live exits.
    """

    def __init__(self, log_lines: deque) -> None:
        super().__init__()
        self.log_lines = log_lines

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.log_lines.append(self.format(record))
        except Exception:
            self.handleError(record)
