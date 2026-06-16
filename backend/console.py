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

logger = logging.getLogger("ipmilink.console")


def _banner_line_count() -> int:
    """Number of rows the big ANSI Shadow banner occupies (for sizing the pinned header).

    Imported lazily inside the function so backend.console stays import-safe on Linux (pyfiglet is
    a declared dep but the banner is only ever rendered on the interactive Windows host) and so a
    broken pyfiglet install degrades to the plain APP_NAME line count instead of crashing the
    header sizing. Computed from branding.banner() so HEADER_SIZE auto-adapts when APP_NAME changes
    in 04.2 — never hardcode a guessed banner height.
    """
    from backend.core.branding import render_banner_safe

    return len(render_banner_safe().splitlines())


# Overhead rows the pinned header reserves BELOW the big banner: 1 blank separator + up to 2
# wrapped help-bar rows (the 9 key hints exceed a ~76-col interior at 80 cols and legitimately wrap)
# + 1 status line + 1 credits line + the Panel's 2 border rows = 7. Kept as a named constant so the
# sizing math (HEADER_SIZE = banner rows + overhead) is explicit and auto-adapts to APP_NAME.
_HEADER_OVERHEAD = 7

# Sentinel returned by read_key() for a consumed special key (Windows arrow/function/nav, where
# msvcrt.getwch() yields a '\x00'/'\xe0' prefix + a scan code). dispatch() treats it as a no-op so
# arrow keys never collide with a real binding or surface as a confusing unknown-key event.
IGNORE_KEY = "\x00__IGNORE__"

# msvcrt.getwch() returns one of these as a PREFIX byte for an extended (non-printable) key; the
# very next getwch() returns the scan code that identifies the actual key. We consume both.
_WIN_EXTENDED_PREFIXES = ("\x00", "\xe0")


# The bind-wildcard hosts. These mean "listen on every interface" — they are NOT navigable
# addresses, so a dashboard URL built from one (e.g. http://0.0.0.0:8099) is not browsable.
_BIND_WILDCARDS = ("0.0.0.0", "::", "")


# Per-severity colour for the on-screen log LEVEL token only (04.1-04 gap-closure r8 — the user
# asked to colour "solo alla scritta info o altro", i.e. just the INFO/WARNING/… word). Applied as a
# rich style SPAN on the level token (NOT markup), so it stays markup-safe and auto-degrades to
# monochrome when the terminal lacks colour / NO_COLOR is set (rich does this by default — we never
# force_terminal). An unknown level falls back to "" (no style) via LEVEL_STYLES.get(name, "").
LEVEL_STYLES = {
    "DEBUG": "dim cyan",
    "INFO": "green",
    "WARNING": "yellow",
    "ERROR": "bold red",
    "CRITICAL": "bold white on red",
}

# On-screen log timestamp format (r8 readability ask): just HH:MM:SS — no date, no ',mmm' millis.
# This is the ON-SCREEN tail only; the full-history file/stderr logging after Live exits is
# unaffected (it keeps its own basicConfig format).
_SCREEN_TIME_FMT = "%H:%M:%S"

# Default (neutral) style for a _push_log action-result line — no emphasis. Prominent/red/cyan
# styles are passed explicitly by the call sites that want their result to stand out (r8).
_PUSH_LOG_DEFAULT_STYLE = ""


def browsable_host(host: str) -> str:
    """Map a bind-wildcard host to a browsable loopback address (D-15a).

    ``0.0.0.0`` / ``::`` / ``""`` are bind-wildcards (listen-on-all), not addresses a browser can
    open — so the show-URL action (key 'u') would otherwise surface an unclickable
    ``http://0.0.0.0:port``. This maps any wildcard to ``127.0.0.1`` (we use the IPv4 loopback even
    for ``::`` for simplicity — it is reachable on every dual-stack host) and leaves a concrete
    host (LAN IP / hostname) unchanged. Pure/stdin-free so it is unit-testable.
    """
    return "127.0.0.1" if (host or "") in _BIND_WILDCARDS else host


def browsable_url(scheme: str, host: str, port: int) -> str:
    """Build a browsable ``scheme://host:port`` URL, mapping a wildcard bind host to loopback.

    Thin wrapper over :func:`browsable_host` so cli()'s get_url callback (and tests) get a single
    pure builder. The wildcard → 127.0.0.1 rewrite is the MUST (browsability); the caller decides
    whether to additionally render it as a clickable terminal hyperlink.
    """
    return f"{scheme}://{browsable_host(host)}:{port}"


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
    Returns the character read, ``IGNORE_KEY`` for a consumed special key (Windows arrow/function/
    nav — a two-call '\\x00'/'\\xe0' prefix + scan-code sequence), or None if no keypress backend is
    available (e.g. a stripped POSIX image without termios).
    """
    if sys.platform == "win32":
        import msvcrt  # guarded: Windows-only (D-23)

        ch = msvcrt.getwch()  # getwch = unicode, no echo
        if ch in _WIN_EXTENDED_PREFIXES:
            # Extended key (arrow/F-key/nav): consume the follow-up scan code so it is NOT
            # dispatched as a stray, possibly-colliding event, and return the ignore sentinel.
            msvcrt.getwch()
            return IGNORE_KEY
        return ch
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
                # Log before exiting so a future getwch()/termios failure is diagnosable instead
                # of the daemon key thread dying silently (no trace, "no key works").
                logger.exception("Key listener stopped: read_key() raised")
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
    """A logging.Handler that appends each record as a STYLED rich Text to a bounded deque (D-01/D-25/r8).

    This is the on-screen log-tail feed for ConsoleUI: while the rich Live render owns the screen,
    log records land in the deque (rendered into the body region) instead of writing to stdout and
    corrupting the Live frame (RESEARCH Pitfall 6). The deque's ``maxlen`` bounds the on-screen
    scrollback (accepted tradeoff — see module docstring); the full history still goes to the
    normal log file/stderr handlers once Live exits.

    R8 READABILITY + COLOUR: each record is stored as a ``rich.text.Text`` built from per-part STYLE
    SPANS (NOT a formatted markup string), so the body can colour the level token and de-emphasise
    the chrome while staying MARKUP-SAFE (r4) — brackets in the message are inert literal characters
    that can NEVER trip rich's markup parser. The per-part styles are:
      • timestamp (HH:MM:SS — readable, no date/millis) → ``dim``
      • level name (padded) → :data:`LEVEL_STYLES` by severity (INFO green, WARNING yellow, …)
      • logger name → ``dim``
      • message (``record.getMessage()``) → default (no style)
      • any exc_info/exc_text traceback → appended after the message as ``dim`` so multi-line
        tracebacks still render in the body.
    Colours degrade to monochrome automatically off-colour terminals (rich default; never forced).
    """

    def __init__(self, log_lines: deque) -> None:
        super().__init__()
        self.log_lines = log_lines

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.log_lines.append(self._build_text(record))
        except Exception:
            self.handleError(record)

    def _build_text(self, record: logging.LogRecord):
        """Build the styled rich Text for one record (r8) — markup-safe (.append spans, no markup).

        Lazy-imports rich.text so the module stays import-safe on Linux (D-23): DequeLogHandler is
        only ever constructed on the interactive Windows host inside run(), but the import is kept
        inside the method so merely importing backend.console (or constructing a handler) never
        requires rich at module-import time on a stripped POSIX image.
        """
        from rich.text import Text

        # A self-contained Formatter (datefmt=HH:MM:SS) does the time + traceback formatting so the
        # on-screen tail is independent of any handler-level formatter (the unit test constructs a
        # bare DequeLogHandler with no setFormatter). formatTime/formatException live on Formatter,
        # NOT on Handler, so we must format through one. Readable HH:MM:SS — no date, no comma-millis.
        fmt = logging.Formatter(datefmt=_SCREEN_TIME_FMT)
        ts = fmt.formatTime(record, _SCREEN_TIME_FMT)
        level = record.levelname
        text = Text()
        text.append(ts, style="dim")
        text.append(" ")
        # Pad the level name to a fixed width so the columns line up; colour JUST the level token
        # (the user asked for "solo alla scritta info o altro"). Unknown levels → "" (no style).
        text.append(f"{level:<8}", style=LEVEL_STYLES.get(level, ""))
        text.append(" ")
        text.append(record.name, style="dim")
        text.append(": ")
        # The message is rendered VERBATIM with no style — getMessage() does the %-arg interpolation.
        text.append(record.getMessage())
        # Append any traceback (exc_info/exc_text) after the message so multi-line tracebacks from a
        # real-R720 polling failure still render in the body. dim so they don't shout over messages.
        exc_text = record.exc_text
        if exc_text is None and record.exc_info:
            exc_text = fmt.formatException(record.exc_info)
        if exc_text:
            text.append("\n")
            text.append(exc_text, style="dim")
        return text


class ConsoleUI:
    """Pinned-header + scrolling-log interactive console (D-01..D-04/D-11/D-13/D-14/D-15a/b/d/D-19).

    Renders a fixed top header (the big ANSI Shadow banner + a help/shortcut bar listing every
    action key + a status line with the active verbosity and the connected-client count + the
    credits line) over a deque-backed scrolling-log body, via rich Live(screen=True) + Layout.
    Action keys dispatch to sub-views (connected sessions / configured servers / show-URL /
    update-stub), cycle the runtime verbosity (starting at INFO per D-04), and run the D-15d
    change-bind-host/port flow.

    SCROLLBACK / HANDLER tradeoffs are documented in the module docstring (Pitfall 1 / Pitfall 6).
    NOTE (04.1-04 gap-closure r3, user override of D-02 "poi compatto"): the big multi-line ANSI
    Shadow banner is PINNED PERMANENTLY in the header (coloured), with the help bar + status +
    credits below it — it is no longer a transient launch splash. HEADER_SIZE is computed from the
    actual banner height (so it auto-adapts to APP_NAME in 04.2) plus an overhead that reserves the
    blank separator + the help bar (which may WRAP to 2 rows at 80 cols) + status + credits + the
    Panel borders, so NOTHING clips at 80 OR 120 cols; the body region (logs) flexes to fill the
    rest. On a narrow terminal the help bar WRAPS (overflow="fold") rather than truncating.

    Callback-driven so it never imports backend.main — Plan 04 passes the real implementations:
      get_url()           -> dashboard address scheme://host:port (D-15a)
      get_servers()       -> read-only list of configured servers + online state (D-15b)
      on_exit()           -> flip server.should_exit so lifespan shutdown runs (D-12)
      on_restart()        -> clean in-process restart (D-15c)
      on_set_verbosity(l) -> apply_log_level + persist the chosen level (D-11/D-25)
      on_change_bind(h,p) -> persist host/port + "restart required" (D-15d)
      get_bind()          -> current (host, port) shown as a READ-ONLY LABEL in the change-bind
                             editor prompt (D-15d r6) so the operator sees the value in effect while
                             the editable buffer starts EMPTY (typing the new value shows it
                             immediately); OPTIONAL — None just omits the "current:" label.
    """

    # Re-exported so callers/tests reference the sentinel via the class (ConsoleUI.IGNORE_KEY).
    IGNORE_KEY = IGNORE_KEY

    # Fixed height of the pinned-header Layout region, in rows. Computed from the ACTUAL big-banner
    # height plus _HEADER_OVERHEAD (blank separator + up-to-2 wrapped help-bar rows + status +
    # credits + 2 panel-border rows), NOT a hardcoded guess — so it auto-adapts when APP_NAME (and
    # thus the banner's line count) changes in 04.2 and the big banner + help bar + status + credits
    # never clip at 80 OR 120 cols (04.1-04 gap-closure r3). The body region (logs) flexes to fill
    # whatever rows remain below the header.
    HEADER_SIZE = _banner_line_count() + _HEADER_OVERHEAD

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
        get_bind=None,
    ) -> None:
        self.ws_manager = ws_manager
        self.get_url = get_url
        self.get_servers = get_servers
        self.on_exit = on_exit
        self.on_restart = on_restart
        self.on_set_verbosity = on_set_verbosity
        self.on_change_bind = on_change_bind
        # OPTIONAL (D-15d r6): returns the current (host, port) shown as a READ-ONLY LABEL in the
        # change-bind editor prompt. The editable buffer stays EMPTY (NOT pre-filled) so the typed
        # value shows immediately. None (default) just omits the "current:" label — backward compat.
        self.get_bind = get_bind
        self.verbosity = verbosity  # D-04: default/quiet == INFO
        self.log_lines: deque = deque(maxlen=max_log_lines)
        self.view = "log"  # "log" | "sessions" | "servers"
        # D-15d keystroke-driven bind editor (replaces the loop-blocking input() prompt):
        #   input_mode is None normally, "bind" while editing the host:port; input_buffer holds the
        #   chars typed so far. dispatch() routes keys to the buffer while input_mode is set so the
        #   editor reuses the EXISTING key listener and NEVER calls input() on the loop thread.
        self.input_mode: str | None = None  # None | "bind"
        self.input_buffer: str = ""
        self.last_key: str | None = None  # last ACTIONABLE key, shown in the header for feedback
        self._stop = threading.Event()
        self._log_handler: logging.Handler | None = None

        # Lazy-import rich so the module stays import-safe on Linux (D-23). The Layout is built
        # once: a fixed-size top header + a flexing body (D-01). HEADER_SIZE is computed from the
        # big banner's actual height + overhead so the banner + help bar/status/credits never clip.
        from rich.layout import Layout

        self.layout = Layout()
        self.layout.split_column(
            # big ANSI Shadow banner + help bar + status + credits (fixed, never scrolls)
            Layout(name="header", size=self.HEADER_SIZE),
            Layout(name="body"),  # log tail OR a sub-view table (flexes)
        )

    # --- helpers ---------------------------------------------------------------------------

    def _push_log(self, line: str, style: str = _PUSH_LOG_DEFAULT_STYLE) -> None:
        """Surface a one-line action result (URL, update stub, change-bind confirmation) in the body.

        R8: stores a styled ``rich.text.Text`` (consistent with DequeLogHandler now storing Text) so
        an action result can stand out — e.g. the change-bind "restart required" confirmation in a
        PROMINENT colour, an invalid bind in red, the URL in cyan. The Text is built with a STYLE
        SPAN (NOT markup), so a line containing '[' is still inert/literal (markup-safety preserved).
        ``style`` defaults to neutral (no emphasis); a plain string call still works (backward-compat).
        Lazy-imports rich.text so the module stays import-safe on Linux (D-23).
        """
        from rich.text import Text

        # Apply the style as a SPAN over the whole line (stylize) rather than the Text-object-level
        # `style=` arg, so it composes cleanly when render_body() joins entries into one Text and the
        # style travels with this line's character range (object-level style would not survive the
        # join). An empty style is a no-op span (neutral default).
        text = Text(line)
        if style:
            text.stylize(style)
        self.log_lines.append(text)

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
        """Build the pinned header: the BIG ANSI Shadow banner + help bar + status + credits (D-01/D-02/D-10).

        The big multi-line ANSI Shadow banner is PINNED PERMANENTLY (coloured bold cyan), with the
        help/shortcut bar, the status line and the credits line stacked below it — this is the
        04.1-04 gap-closure r3 user override of D-02's "poi compatto" (the banner stays visible all
        session instead of being a one-time splash). HEADER_SIZE reserves enough rows (banner height
        + overhead) that none of the banner / help bar / status / credits is ever clipped at 80 OR
        120 cols. Key hints in the help bar are bracket-escaped so '[v]'/'[q]' render literally
        instead of being eaten as rich markup; each banner line is escaped too so its block/box-draw
        glyphs (█ ╗ ═ ║ …) never collide with rich markup. Colours are rich markup (D-02/D-05) and
        degrade to monochrome automatically when the terminal lacks colour or NO_COLOR is set.

        render_banner_safe() (not banner()) is used so a broken pyfiglet install degrades the header
        to the plain APP_NAME line instead of crashing the render loop — the header must never die.
        """
        from rich.markup import escape
        from rich.panel import Panel
        from rich.text import Text

        from backend.core.branding import AUTHOR, LICENSE, VERSION, render_banner_safe

        # The big ANSI Shadow banner, PINNED in the header (D-02 "a colori"). Escape EACH line so the
        # block/box-draw glyphs never trip rich's markup parser, then colour the whole block cyan.
        banner_lines = render_banner_safe().splitlines()
        brand = "\n".join(f"[bold cyan]{escape(line)}[/bold cyan]" for line in banner_lines)

        # Bracket-escape the key hints so '[v]' etc. survive rich markup; colour only the keys.
        keys = [
            ("v", "verbosity"),
            ("c", "sessions"),
            ("s", "servers"),
            ("u", "url"),
            ("g", "update"),
            ("b", "change bind"),
            ("r", "restart"),
            ("q", "quit"),
            ("ESC", "back"),
        ]
        help_bar = "  ".join(
            f"[bold yellow]{escape(f'[{k}]')}[/bold yellow] {escape(label)}" for k, label in keys
        )

        last = self.last_key if self.last_key is not None else "-"
        # While the D-15d bind editor is active, the help row becomes a live entry prompt that
        # shows the host:port format, how to confirm/cancel, and the current buffer — so the
        # operator gets visible feedback for every keystroke (the editor reuses the key listener).
        # It REPLACES the help bar (not the status/credits) so the bind editor never regresses.
        # D-15d r6 (UX correction of r5): the prompt shows the current bind as a READ-ONLY LABEL
        # ("current: host:port") while the editable buffer (the "new:" field) starts EMPTY — so the
        # operator's typed value shows immediately and is NOT confused with a pre-filled value
        # (r5 pre-filled the buffer; typing then appeared to "do nothing"). When get_bind is None or
        # raises, the "current:" label is omitted and the generic host:port prompt is shown. The
        # current-bind label AND the buffer are bracket-escaped (round-4 markup-safety) so a value
        # containing '[' never crashes the render.
        if self.input_mode == "bind":
            current = None
            if self.get_bind is not None:
                try:
                    ch, cp = self.get_bind()
                    current = f"{ch}:{cp}"
                except Exception:
                    current = None
            if current is not None:
                action_line = (
                    f"[bold yellow]Change bind — current: {escape(current)}[/bold yellow]  "
                    "[dim]→[/dim]  [bold]new:[/bold] "
                    f"[cyan]{escape(self.input_buffer)}[/cyan]   "
                    "[dim](Enter=apply, ESC=cancel, Backspace=del)[/dim]"
                )
            else:
                action_line = (
                    "[bold yellow]Enter new bind as host:port[/bold yellow]  "
                    "[dim](Enter=confirm, ESC=cancel, Backspace=del):[/dim] "
                    f"[cyan]{escape(self.input_buffer)}[/cyan]"
                )
        else:
            action_line = help_bar
        status = (
            f"[dim]Verbosity:[/dim] [green]{escape(self.verbosity)}[/green]  "
            f"[dim]|[/dim]  [dim]Clients:[/dim] {self.ws_manager.connection_count}  "
            f"[dim]|[/dim]  [dim]last:[/dim] [magenta]{escape(str(last))}[/magenta]"
        )
        # Compact one-line credits for the PINNED header (the full credits_line() incl. the long
        # repo URL is shown once in `docker logs` via lifespan — main.py — where it has full width).
        credits = f"[dim]{escape(f'{AUTHOR} · v{VERSION} · {LICENSE}')}[/dim]"

        # banner block, a blank separator, then the action line (help bar OR bind prompt), status,
        # credits. A leading blank separator gives the big banner breathing room from the help bar.
        body = Text.from_markup("\n".join([brand, "", action_line, status, credits]))
        # no_wrap=False (default) so the help bar WRAPS rather than truncates on a narrow terminal
        # (REVIEWS LOW: graceful degrade); overflow="fold" keeps every char reachable.
        body.overflow = "fold"
        return Panel(body, title=Text.from_markup("[bold]Console[/bold]"))

    def render_body(self):
        """Render the body for the active view: the log tail, the sessions table, or the server table.

        MARKUP-SAFETY (04.1-04 gap-closure r4 — the console-freeze fix): every piece of arbitrary
        text rendered here (log lines, table cell values) is wrapped in rich.text.Text, which does
        NOT parse console markup. Previously the log body was Panel("\\n".join(self.log_lines)) —
        rich parses that string as MARKUP by default, so a log line containing an unmatched '[/]', a
        mismatched '[/italic]' or any '[tag]' (object reprs, SQL, BMC output all contain brackets)
        raised rich.errors.MarkupError at render time, inside the while-loop under Live(screen=True).
        That exception killed the render thread → the screen froze and never re-rendered (the 'last:'
        indicator stuck, "nothing shows"). Wrapping the content in Text makes brackets inert literal
        characters, so an arbitrary log line / IP / User-Agent / hostname can NEVER crash the render.
        """
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text

        if self.view == "sessions":
            table = Table(title="Connected sessions")  # D-14/D-19
            table.add_column("IP")
            table.add_column("Connected since")
            table.add_column("User-Agent")
            for row in self.ws_manager.sessions():
                # Text() per cell so an odd IP / User-Agent containing '[' is literal, not markup.
                table.add_row(
                    Text(str(row.get("ip", ""))),
                    Text(str(row.get("connected_since", ""))),
                    Text(str(row.get("user_agent", ""))),
                )
            return table
        if self.view == "servers":
            table = Table(title="Configured servers")  # D-15b (read-only)
            table.add_column("Name")
            table.add_column("Host")
            table.add_column("Status")
            for srv in self.get_servers():
                # Text() per cell so an odd server name / hostname containing '[' can't crash render.
                table.add_row(
                    Text(str(srv.get("name", ""))),
                    Text(str(srv.get("host", ""))),
                    Text(str(srv.get("status", ""))),
                )
            return table
        # default: the scrolling-log view (last N lines of the deque). The deque now holds styled
        # rich Text entries (DequeLogHandler / _push_log both store Text — r8), so we JOIN them into
        # ONE Text with newline separators rather than "\n".join()-ing strings. Any stray str entry
        # (a backward-compat / future-regression raw push) is defensively coerced to Text(entry) so a
        # mixed deque can never raise. Joining Text objects preserves every per-part style span and
        # stays MARKUP-SAFE (Text is never parsed as markup), so the readable timestamp, the coloured
        # level token and the prominent action-result lines all render while markup-like content in
        # any line is still inert. Result remains a single renderable inside the Panel.
        entries = [e if isinstance(e, Text) else Text(str(e)) for e in self.log_lines]
        body = Text("\n").join(entries) if entries else Text("")
        return Panel(body, title="Logs")

    # --- interaction -----------------------------------------------------------------------

    @staticmethod
    def parse_bind(buffer: str) -> tuple[str, int] | None:
        """Pure parse+validate of a 'host:port' buffer for the D-15d editor (stdin-free, testable).

        Splits on the LAST ':' (so IPv6-ish hosts and hostnames with no colon both behave sanely),
        requires BOTH a host and a port to be present, then delegates to _validate_bind(). Returns
        (host, port) on success, None on any malformed/empty/out-of-range input.
        """
        if ":" not in buffer:
            return None
        host, _, port_str = buffer.rpartition(":")
        return ConsoleUI._validate_bind(host, port_str)

    def _enter_bind_edit(self) -> None:
        """Enter the keystroke-driven bind editor (key 'b'): flip input_mode, EMPTY the buffer.

        Deliberately does NO blocking I/O — it only sets state. While input_mode == "bind" the
        normal action keys are suspended and dispatch() routes each keypress to input_buffer, so
        the existing key listener drives the edit and the asyncio loop thread is NEVER blocked
        (the old input()-based prompt blocked the loop and fought the key thread → console freeze).

        D-15d r6 (UX correction of r5): the buffer starts EMPTY — it is NOT pre-filled with the
        current bind anymore. r5 pre-filled it with "{host}:{port}", which confused the operator:
        typing a new value appended to / did not visibly replace the pre-filled text ("I typed a new
        bind but nothing happened"). The current bind is instead surfaced as a READ-ONLY LABEL in
        the render_header() prompt (via get_bind), so the operator SEES the value in effect while
        the typed value shows immediately in the empty "new:" field. get_bind is still kept (used by
        the prompt label) but is no longer read here; the buffer is unconditionally empty so the
        typed value IS the new bind (no clearing of a pre-fill needed).
        """
        self.input_mode = "bind"
        self.input_buffer = ""

    def _cancel_input(self) -> None:
        """Leave any input mode without committing (ESC) — clears the editor state."""
        self.input_mode = None
        self.input_buffer = ""

    def _commit_bind(self) -> None:
        """Confirm the bind editor (Enter): parse the buffer, apply on success, then exit edit mode.

        On a valid 'host:port' it calls on_change_bind(host, port) and pushes the existing
        "restart required" confirmation; on invalid input it pushes "Invalid host/port" and the
        callback is NOT called. Either way the editor state is cleared (no lingering buffer).
        """
        result = self.parse_bind(self.input_buffer)
        if result is None:
            # Rejection — red so the operator clearly sees the change was NOT applied (r8).
            self._push_log(
                f"Invalid host/port '{self.input_buffer}' — change cancelled", style="bold red"
            )
            self._cancel_input()
            return
        host, port = result
        self.on_change_bind(host, port)
        # The user's MAIN r8 ask: make this action result stand out — bold green so the
        # "restart required to apply" prompt is unmissable in the scrolling log body.
        self._push_log(
            f"Bind set to {host}:{port} — restart required to apply (press r)", style="bold green"
        )
        self._cancel_input()

    def _dispatch_input(self, key: str) -> None:
        """Route a keypress to the active input editor (currently only the D-15d bind editor).

        Enter ('\\r'/'\\n') confirms, ESC ('\\x1b') cancels, Backspace ('\\x08'/'\\x7f') deletes the
        last char, and any other single printable char appends to the buffer. The IGNORE_KEY
        sentinel / None are filtered by dispatch() before we get here, so an arrow key never
        corrupts the buffer. No branch performs a blocking call — this all runs on the loop thread.
        """
        if key in ("\r", "\n"):
            self._commit_bind()
        elif key == "\x1b":  # ESC
            self._cancel_input()
        elif key in ("\x08", "\x7f"):  # Backspace / Delete
            self.input_buffer = self.input_buffer[:-1]
        elif len(key) == 1 and key.isprintable():
            self.input_buffer += key
        # anything else (stray control char) is ignored — never blocks, never corrupts the buffer

    def dispatch(self, key: str) -> None:
        """Map an action key to its behavior (D-03/D-11/D-13/D-14/D-15a/b/c/d).

        Bindings:
          v   -> cycle verbosity INFO -> DEBUG -> WARNING -> INFO (D-11/D-25)
          c   -> open the connected-sessions sub-view (D-14/D-19)
          s   -> open the configured-servers sub-view (D-15b)
          u   -> push the dashboard URL into the log (D-15a)
          g   -> update-check STUB: print the local version + "ships with the pip release", NO
                 network call (D-13)
          b   -> enter the keystroke-driven change-bind editor (D-15d) — NOT a blocking input()
          r   -> clean in-process restart (D-15c)
          q   -> if in a sub-view, return to the log view; else clean exit (D-03/D-12)
          ESC -> same as q for sub-views (D-03)

        While input_mode is set (the D-15d bind editor), keys are routed to the editor buffer via
        _dispatch_input() instead of the action map, and dispatch() returns early — so typing a
        host:port never triggers an action and no branch ever performs a blocking call on the loop
        thread (the old input() prompt blocked the loop and fought the key thread → console freeze).

        Special keys consumed by read_key() arrive as IGNORE_KEY (or None on a backend-less host)
        and are a NO-OP: they neither fire a callback, feed the input buffer, nor touch the last-key
        feedback (so an arrow key never masquerades as an actionable press). Every ACTIONABLE key
        updates last_key so the operator gets immediate visible confirmation in the header status
        line (04.1-04 fix).
        """
        # Ignore consumed special keys / no-key reads — never collide with a real binding (or
        # corrupt the bind-edit buffer). This guard stays first so IGNORE_KEY is inert everywhere.
        if key is None or key == IGNORE_KEY:
            return

        # While an input editor is active (D-15d bind edit) every key feeds the buffer, NOT the
        # action map — and we return early so no action fires while typing. No blocking call.
        if self.input_mode is not None:
            self._dispatch_input(key)
            return

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
            # D-15a: push the (browsable) dashboard URL. get_url() already rewrites a wildcard
            # bind to 127.0.0.1 (cli() uses browsable_url), so this is always navigable. The URL is
            # carried by a Text STYLE SPAN ("cyan", r8) so it stands out from ordinary log noise —
            # NOT rich link markup ('[link=…]'): a Text span is inherently markup-safe (brackets in
            # any other log line stay literal), whereas markup would force render_body to parse
            # '[...]' in EVERY entry (BMC output, etc.) and could corrupt the frame. Browsability is
            # the MUST; a clickable OSC-8 hyperlink is a nice-to-have not worth that risk.
            self._push_log(self.get_url(), style="cyan")
        elif key == "g":
            # Informational stub — neutral (default) style; not an alert (r8).
            self._push_log(
                f"Current version {VERSION}. Online update check ships with the pip release."
            )
        elif key == "b":
            # D-15d: enter the keystroke-driven bind editor (no input(), never blocks the loop).
            self._enter_bind_edit()
        elif key == "r":
            self.on_restart()
        elif key in ("q", "\x1b"):
            if self.view != "log":
                self.view = "log"
            else:
                self.on_exit()

        # Visible feedback: record the actionable key for the header status line (04.1-04).
        self.last_key = key

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

    @staticmethod
    def _suspend_stream_handlers() -> list[logging.Handler]:
        """Remove the root logger's StreamHandlers so logging does not fight the Live frame (r7).

        FLICKER FIX (04.1-04 gap-closure r7): run() adds a DequeLogHandler so log records render in
        the body region, but the pre-existing StreamHandler (installed by logging.basicConfig() in
        lifespan) was NEVER removed. Every record then went to BOTH handlers — the StreamHandler
        wrote straight to stderr, bypassing rich Live's redirect and fighting the screen frame
        (visible flicker), and the frequent multi-line ERROR tracebacks (real-R720 polling failures)
        escaped the box → frame breakdown (raw logs outside the borders). This snapshots and removes
        every root StreamHandler (EXCLUDING the DequeLogHandler — which is a logging.Handler, not a
        StreamHandler, but the explicit guard keeps it safe) so while Live owns the screen logging
        goes ONLY to the deque (rendered in the body). Returns the removed handlers for restore().

        Idempotent: 0 stream handlers → returns [] (no-op). Safe across restarts: run() is called
        per restart and each call removes+restores ITS OWN snapshot. Never reached off a TTY (run()
        returns early on `not is_interactive()`), so the Docker/non-TTY path keeps its stderr logs.
        """
        saved: list[logging.Handler] = []
        root_logger = logging.getLogger()
        for h in list(root_logger.handlers):
            if isinstance(h, logging.StreamHandler) and not isinstance(h, DequeLogHandler):
                saved.append(h)
                root_logger.removeHandler(h)
        return saved

    @staticmethod
    def _restore_stream_handlers(saved: list[logging.Handler]) -> None:
        """Re-add the StreamHandlers suspended by _suspend_stream_handlers() (restore on Live exit).

        Restores normal stderr logging once Live releases the screen. restore([]) is a no-op so the
        zero-stream-handler case (and a double restore) never raises.
        """
        root_logger = logging.getLogger()
        for h in saved:
            root_logger.addHandler(h)

    def run(self) -> None:
        """Run the interactive render loop — no-op off a TTY (D-24/D-07).

        Gates on is_interactive() first: on a non-TTY (Docker/systemd/piped) it returns immediately
        and the caller keeps plain scrolling logs. On a TTY it installs a DequeLogHandler on the
        root logger so log records render in the body instead of fighting the Live frame (Pitfall
        6), SUSPENDS the pre-existing root StreamHandlers for the lifetime of Live so log records
        go ONLY to the deque (r7 flicker fix — the StreamHandler was bypassing Live's redirect and
        fighting the frame), then runs Live(screen=True) until stop() is signalled. In finally it
        calls stop() (removes the DequeLogHandler) and restores the suspended StreamHandlers so
        normal stdout/stderr logging resumes. Logs still flow to the normal log file/stderr for the
        full history once Live exits.
        """
        if not is_interactive():
            return

        import time

        from rich.console import Console
        from rich.live import Live

        console = Console()  # NEVER force_terminal/force_interactive (D-24)
        handler = DequeLogHandler(self.log_lines)
        # No setFormatter needed (r8): DequeLogHandler now builds a styled rich Text per record in
        # _build_text() (readable HH:MM:SS time + colour-coded level token via LEVEL_STYLES), using
        # its own self-contained Formatter for the time/traceback — it does NOT consume a handler-
        # level format string anymore. The full-history file/stderr logging after Live exits keeps
        # its own basicConfig format (unaffected).
        self._log_handler = handler
        logging.getLogger().addHandler(handler)
        # r7 FLICKER FIX: suspend the pre-existing root StreamHandlers (basicConfig's stderr handler)
        # for the lifetime of Live so log records go ONLY to the deque (rendered in the body) and
        # never bypass Live's redirect to fight the frame. Restored in finally. See the helper.
        saved_stream_handlers = self._suspend_stream_handlers()
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
                    # RESILIENT RENDER (04.1-04 gap-closure r4 — belt-and-suspenders): guard the
                    # per-frame render so a SINGLE bad frame can NEVER kill the render thread again
                    # (that was the console-freeze bug — a MarkupError from a log line propagated out
                    # of this loop, the thread died, the screen froze). Markup-safety in
                    # render_body()/render_header() is the primary fix; this is the safety net for
                    # any future renderable that could raise. On a render error we log it (to the
                    # module logger AND, since the DequeLogHandler is attached, into the on-screen
                    # body) and continue — the loop keeps running until stop() is signalled. We
                    # deliberately do NOT guard the loop condition itself, so _stop still exits.
                    try:
                        self.layout["header"].update(self.render_header())
                        self.layout["body"].update(self.render_body())
                    except Exception:
                        logger.exception("Console render frame failed — continuing")
                    time.sleep(0.25)
        finally:
            self.stop()  # remove the DequeLogHandler — restore normal stdout logging
            # r7: restore the StreamHandlers suspended above so normal stderr logging resumes once
            # Live has released the screen (idempotent — restore([]) is a no-op on the 0-handler case).
            self._restore_stream_handlers(saved_stream_handlers)
