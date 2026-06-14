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


class ConsoleUI:
    """Pinned-header + scrolling-log interactive console (D-01..D-04/D-11/D-13/D-14/D-15a/b/d/D-19).

    Renders a fixed top header (compact banner + a help/shortcut bar listing every action key + a
    status line with the active verbosity and the connected-client count + the credits line) over
    a deque-backed scrolling-log body, via rich Live(screen=True) + Layout. Action keys dispatch to
    sub-views (connected sessions / configured servers / show-URL / update-stub), cycle the runtime
    verbosity (starting at INFO per D-04), and run the D-15d change-bind-host/port flow.

    SCROLLBACK / HANDLER tradeoffs are documented in the module docstring (Pitfall 1 / Pitfall 6).
    NOTE (REVIEWS LOW): the header is a fixed size; if a figlet font + help bar overflows a narrow
    terminal the compact banner is used and the help bar is allowed to wrap.

    Callback-driven so it never imports backend.main — Plan 04 passes the real implementations:
      get_url()           -> dashboard address scheme://host:port (D-15a)
      get_servers()       -> read-only list of configured servers + online state (D-15b)
      on_exit()           -> flip server.should_exit so lifespan shutdown runs (D-12)
      on_restart()        -> clean in-process restart (D-15c)
      on_set_verbosity(l) -> apply_log_level + persist the chosen level (D-11/D-25)
      on_change_bind(h,p) -> persist host/port + "restart required" (D-15d)
    """

    def __init__(
        self,
        ws_manager,
        get_url,
        get_servers,
        on_exit,
        on_restart,
        on_set_verbosity,
        on_change_bind,
        verbosity: str = "INFO",
        max_log_lines: int = 500,
    ) -> None:
        self.ws_manager = ws_manager
        self.get_url = get_url
        self.get_servers = get_servers
        self.on_exit = on_exit
        self.on_restart = on_restart
        self.on_set_verbosity = on_set_verbosity
        self.on_change_bind = on_change_bind
        self.verbosity = verbosity  # D-04: default/quiet == INFO
        self.log_lines: deque = deque(maxlen=max_log_lines)
        self.view = "log"  # "log" | "sessions" | "servers"
        self._stop = threading.Event()
        self._log_handler: logging.Handler | None = None

        # Lazy-import rich so the module stays import-safe on Linux (D-23). The Layout is built
        # once: a fixed-size top header + a flexing body (D-01).
        from rich.layout import Layout

        self.layout = Layout()
        self.layout.split_column(
            Layout(name="header", size=8),  # banner + help bar + status (fixed, never scrolls)
            Layout(name="body"),  # log tail OR a sub-view table (flexes)
        )

    # --- helpers ---------------------------------------------------------------------------

    def _push_log(self, line: str) -> None:
        """Surface a one-line action result (URL, update stub, change-bind confirmation) in the body."""
        self.log_lines.append(line)

    @staticmethod
    def _validate_bind(host: str, port_str: str) -> tuple[str, int] | None:
        """Pure, stdin-free validation for the D-15d change-bind flow (so it is unit-testable).

        Accepts a non-empty host (0.0.0.0 / 127.0.0.1 / hostnames) and a port that is an int in
        1..65535. Returns (host, port) on success, None on any invalid input.
        """
        host = (host or "").strip()
        if not host:
            return None
        try:
            port = int(port_str)
        except (TypeError, ValueError):
            return None
        if port < 1 or port > 65535:
            return None
        return (host, port)

    # --- rendering -------------------------------------------------------------------------

    def render_header(self):
        """Build the pinned header: compact banner + help/shortcut bar + status + credits (D-01/D-02/D-10)."""
        from rich.panel import Panel

        from backend.core.branding import banner, credits_line

        help_bar = (
            "[v] verbosity  [c] sessions  [s] servers  [u] url  "
            "[g] update  [b] change bind  [r] restart  [q] quit  [ESC] back"
        )
        status = (
            f"Verbosity: {self.verbosity} | Clients: {self.ws_manager.connection_count}"
        )
        body = "\n".join([banner(compact=True), "", help_bar, status, credits_line()])
        return Panel(body, title="IPMILink")

    def render_body(self):
        """Render the body for the active view: the log tail, the sessions table, or the server table."""
        from rich.panel import Panel
        from rich.table import Table

        if self.view == "sessions":
            table = Table(title="Connected sessions")  # D-14/D-19
            table.add_column("IP")
            table.add_column("Connected since")
            table.add_column("User-Agent")
            for row in self.ws_manager.sessions():
                table.add_row(
                    str(row.get("ip", "")),
                    str(row.get("connected_since", "")),
                    str(row.get("user_agent", "")),
                )
            return table
        if self.view == "servers":
            table = Table(title="Configured servers")  # D-15b (read-only)
            table.add_column("Name")
            table.add_column("Host")
            table.add_column("Status")
            for srv in self.get_servers():
                table.add_row(
                    str(srv.get("name", "")),
                    str(srv.get("host", "")),
                    str(srv.get("status", "")),
                )
            return table
        # default: the scrolling-log view (last N lines of the deque)
        return Panel("\n".join(self.log_lines), title="Logs")

    # --- interaction -----------------------------------------------------------------------

    def prompt_bind(self) -> tuple[str, int] | None:
        """D-15d input flow: read a host + port from stdin and validate (run() suspends Live around this).

        Plain input() is acceptable because run() already gated on a TTY (D-24). Validation is
        delegated to the pure _validate_bind() helper so the logic is unit-testable without stdin.
        """
        try:
            host = input("New bind host: ")
            port_str = input("New bind port: ")
        except (EOFError, KeyboardInterrupt):
            self._push_log("Change bind cancelled")
            return None
        result = self._validate_bind(host, port_str)
        if result is None:
            self._push_log("Invalid host/port — change cancelled")
            return None
        return result

    def _do_change_bind(self) -> None:
        """Seam for the 'b' key: prompt + validate + invoke on_change_bind (monkeypatched in tests)."""
        result = self.prompt_bind()
        if result is None:
            return
        host, port = result
        self.on_change_bind(host, port)
        self._push_log(f"Bind set to {host}:{port} — restart required to apply (press r)")

    def dispatch(self, key: str) -> None:
        """Map an action key to its behavior (D-03/D-11/D-13/D-14/D-15a/b/c/d).

        Bindings:
          v   -> cycle verbosity INFO -> DEBUG -> WARNING -> INFO (D-11/D-25)
          c   -> open the connected-sessions sub-view (D-14/D-19)
          s   -> open the configured-servers sub-view (D-15b)
          u   -> push the dashboard URL into the log (D-15a)
          g   -> update-check STUB: print the local version + "ships with the pip release", NO
                 network call (D-13)
          b   -> change-bind-host/port flow (D-15d)
          r   -> clean in-process restart (D-15c)
          q   -> if in a sub-view, return to the log view; else clean exit (D-03/D-12)
          ESC -> same as q for sub-views (D-03)
        """
        from backend.core.branding import VERSION
        from backend.core.logging_util import next_level

        if key == "v":
            nl = next_level(self.verbosity)
            self.on_set_verbosity(nl)
            self.verbosity = nl
        elif key == "c":
            self.view = "sessions"
        elif key == "s":
            self.view = "servers"
        elif key == "u":
            self._push_log(self.get_url())
        elif key == "g":
            self._push_log(
                f"Current version {VERSION}. Online update check ships with the pip release."
            )
        elif key == "b":
            self._do_change_bind()
        elif key == "r":
            self.on_restart()
        elif key in ("q", "\x1b"):
            if self.view != "log":
                self.view = "log"
            else:
                self.on_exit()

    # --- lifecycle -------------------------------------------------------------------------

    def stop(self) -> None:
        """Signal the render loop to break and restore logging (idempotent).

        Sets the stop event so Plan 04 can tear down the render/key threads on exit/restart, and
        removes the DequeLogHandler from the root logger (restoring normal stdout/stderr logging).
        """
        self._stop.set()
        if self._log_handler is not None:
            logging.getLogger().removeHandler(self._log_handler)
            self._log_handler = None

    def run(self) -> None:
        """Run the interactive render loop — no-op off a TTY (D-24/D-07).

        Gates on is_interactive() first: on a non-TTY (Docker/systemd/piped) it returns immediately
        and the caller keeps plain scrolling logs. On a TTY it installs a DequeLogHandler on the
        root logger so log records render in the body instead of fighting the Live frame (Pitfall
        6), then runs Live(screen=True) until stop() is signalled, and in finally calls stop() to
        remove the handler so normal logging is restored. Logs still flow to the normal log
        file/stderr for the full history once Live exits.
        """
        if not is_interactive():
            return

        import time

        from rich.console import Console
        from rich.live import Live

        console = Console()  # NEVER force_terminal/force_interactive (D-24)
        handler = DequeLogHandler(self.log_lines)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        self._log_handler = handler
        logging.getLogger().addHandler(handler)
        try:
            with Live(
                self.layout,
                console=console,
                screen=True,
                refresh_per_second=4,
                redirect_stdout=True,
                redirect_stderr=True,
            ):
                while not self._stop.is_set():
                    self.layout["header"].update(self.render_header())
                    self.layout["body"].update(self.render_body())
                    time.sleep(0.25)
        finally:
            self.stop()  # remove the DequeLogHandler — restore normal stdout logging
