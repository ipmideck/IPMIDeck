"""Headless ConsoleUI dispatch tests (D-01/D-04/D-11/D-13/D-14/D-15a/b/d).

These exercise the CI-assertable surface of the console: the verbosity cycle (default INFO),
the update stub (no network), sub-view switch + ESC/q return, show-URL, the D-15d change-bind
validation + on_change_bind callback, and stop() (event + handler removal). The full interactive
render (rich Live alternate screen) is NOT exercised here — run() gates on isatty() and is
validated in Plan 04's host UAT. We never call run().

It ALSO locks the 04.1-04 gap-closure fixes (special-key consumption, last-key feedback) and the
r3 header layout: the pinned header must render the BIG ANSI Shadow banner + the help bar + status
+ credits with NO clipping at BOTH 80 AND 120 cols (the banner is now PERMANENTLY pinned — r3 user
override of D-02 "poi compatto"), special arrow/function keys must be consumed as a single
ignorable event, and an actionable keypress must update the header's last-key field.
"""

from __future__ import annotations

import logging
from collections import deque

from backend.console import ConsoleUI
from backend.core.branding import VERSION


def _render_header_text(ui, width: int = 80) -> str:
    """Render ui.render_header() through a fixed-width recording rich Console and return plain text.

    export_text() strips ANSI/markup so assertions are colour-independent; width is pinned so the
    clipping regression is deterministic regardless of the runner's real terminal size.
    """
    from rich.console import Console

    console = Console(width=width, record=True)
    console.print(ui.render_header())
    return console.export_text()


def _render_body_text(ui, width: int = 80) -> str:
    """Render ui.render_body() through a fixed-width recording rich Console and return plain text.

    This is what Live(screen=True) does every frame: it materialises the renderable, parsing rich
    markup. A log line / table cell / bind buffer containing markup-like text ('[/]', '[bold]x[/]')
    would raise rich.errors.MarkupError HERE, killing the render thread and freezing the console
    (the 04.1-04 r4 host-UAT bug). The fix renders all arbitrary text as PLAIN Text, so this never
    raises. Rendered through a recording console so the regression is deterministic (no real Live).
    """
    from rich.console import Console

    console = Console(width=width, record=True)
    console.print(ui.render_body())
    return console.export_text()


class _FakeWSManager:
    """Minimal ws_manager stand-in: empty sessions, zero clients.

    Accepts an optional sessions list so a regression test can feed a session row whose IP /
    User-Agent contains markup-like text ('[') and assert the sessions table still renders.
    """

    def __init__(self, sessions_data: list[dict] | None = None) -> None:
        self._sessions_data = sessions_data if sessions_data is not None else []

    def sessions(self) -> list[dict]:
        return self._sessions_data

    @property
    def connection_count(self) -> int:
        return 0


def _make_ui(**overrides):
    """Build a ConsoleUI with capture-list callbacks. Returns (ui, calls)."""
    calls: dict[str, list] = {
        "set_verbosity": [],
        "exit": [],
        "restart": [],
        "change_bind": [],
    }
    kwargs = dict(
        ws_manager=_FakeWSManager(),
        get_url=lambda: "http://h:3000",
        get_servers=lambda: [],
        on_exit=lambda: calls["exit"].append(True),
        on_restart=lambda: calls["restart"].append(True),
        on_set_verbosity=lambda lvl: calls["set_verbosity"].append(lvl),
        on_change_bind=lambda host, port: calls["change_bind"].append((host, port)),
    )
    kwargs.update(overrides)
    return ConsoleUI(**kwargs), calls


def test_default_verbosity_is_info():
    """A fresh ConsoleUI starts at the D-04 quiet baseline, INFO."""
    ui, _ = _make_ui()
    assert ui.verbosity == "INFO"


def test_verbosity_cycle_calls_callback_and_updates_label():
    """dispatch('v') cycles INFO -> DEBUG -> WARNING -> INFO and notifies on_set_verbosity (D-11)."""
    ui, calls = _make_ui()
    ui.dispatch("v")
    assert calls["set_verbosity"][-1] == "DEBUG"
    assert ui.verbosity == "DEBUG"
    ui.dispatch("v")
    assert calls["set_verbosity"][-1] == "WARNING"
    assert ui.verbosity == "WARNING"
    ui.dispatch("v")
    assert calls["set_verbosity"][-1] == "INFO"
    assert ui.verbosity == "INFO"


def test_update_stub_pushes_version_line_no_network():
    """dispatch('g') is a pure-string stub (D-13): version + 'ships with the pip release', no network."""
    ui, _ = _make_ui()
    ui.dispatch("g")
    last = ui.log_lines[-1]
    assert VERSION in last
    assert "ships with the pip release" in last


def test_sub_view_switch_and_back():
    """dispatch('c') opens sessions; 'q' returns to log (no exit); a 2nd 'q' at log exits (D-03/D-12)."""
    ui, calls = _make_ui()
    ui.dispatch("c")
    assert ui.view == "sessions"
    ui.dispatch("q")
    assert ui.view == "log"
    assert calls["exit"] == []
    ui.dispatch("q")
    assert calls["exit"] == [True]


def test_esc_returns_from_sub_view():
    """ESC behaves like q in a sub-view: returns to the log view (D-03)."""
    ui, calls = _make_ui()
    ui.dispatch("s")
    assert ui.view == "servers"
    ui.dispatch("\x1b")
    assert ui.view == "log"
    assert calls["exit"] == []


def test_show_url_pushes_log():
    """dispatch('u') pushes the dashboard URL into the log body (D-15a).

    r8: the deque now stores styled rich Text entries (so the URL can be coloured cyan), so the
    assertion compares the entry's plain text rather than `== str`.
    """
    ui, _ = _make_ui(get_url=lambda: "http://h:3000")
    ui.dispatch("u")
    assert ui.log_lines[-1].plain == "http://h:3000"


# --- gap-closure r2: browsable URL host mapping (wildcard -> 127.0.0.1) -------------------


def test_browsable_host_maps_wildcards_to_loopback():
    """browsable_host() maps the bind-wildcards 0.0.0.0 / :: / "" to a browsable 127.0.0.1.

    A wildcard bind is NOT a navigable address — pressing 'u' must surface something the operator
    can actually open. A real host (LAN IP / hostname) is returned unchanged.
    """
    from backend.console import browsable_host

    assert browsable_host("0.0.0.0") == "127.0.0.1"
    assert browsable_host("::") == "127.0.0.1"
    assert browsable_host("") == "127.0.0.1"
    # a concrete host is left alone
    assert browsable_host("192.0.2.10") == "192.0.2.10"
    assert browsable_host("myhost.lan") == "myhost.lan"
    assert browsable_host("127.0.0.1") == "127.0.0.1"


def test_browsable_url_rewrites_wildcard_host():
    """browsable_url() rebuilds scheme://host:port with the wildcard host mapped to loopback."""
    from backend.console import browsable_url

    assert browsable_url("http", "0.0.0.0", 8099) == "http://127.0.0.1:8099"
    assert browsable_url("https", "::", 8443) == "https://127.0.0.1:8443"
    assert browsable_url("http", "192.0.2.10", 3000) == "http://192.0.2.10:3000"


def test_show_url_is_browsable_when_bound_to_wildcard():
    """When the bind host is a wildcard, 'u' pushes a browsable 127.0.0.1 URL (not 0.0.0.0)."""
    from backend.console import browsable_url

    ui, _ = _make_ui(get_url=lambda: browsable_url("http", "0.0.0.0", 8099))
    ui.dispatch("u")
    # r8: the deque stores styled Text now — compare the plain text.
    assert ui.log_lines[-1].plain == "http://127.0.0.1:8099"
    assert "0.0.0.0" not in ui.log_lines[-1].plain


def test_validate_bind_accepts_good_and_rejects_bad():
    """_validate_bind accepts a good host/port and rejects empty host, out-of-range and non-int ports."""
    assert ConsoleUI._validate_bind("0.0.0.0", "8099") == ("0.0.0.0", 8099)
    assert ConsoleUI._validate_bind("", "8099") is None
    assert ConsoleUI._validate_bind("h", "0") is None
    assert ConsoleUI._validate_bind("h", "70000") is None
    assert ConsoleUI._validate_bind("h", "abc") is None


# --- gap-closure r2: keystroke-driven bind-edit mode (no input(), no loop block) ---------


def test_b_enters_bind_edit_mode_without_input(monkeypatch):
    """dispatch('b') enters keystroke-driven bind-edit mode and NEVER calls input() (no loop block).

    The old input()-based prompt blocked the asyncio loop thread (the console froze). The new
    editor reuses the existing key listener: 'b' just flips input_mode -> 'bind'; no blocking call.
    """
    import builtins

    def _boom(*_a, **_k):
        raise AssertionError("input() must never be called on the loop thread (freeze regression)")

    monkeypatch.setattr(builtins, "input", _boom)
    ui, calls = _make_ui()
    ui.dispatch("b")
    assert ui.input_mode == "bind"
    assert ui.input_buffer == ""
    assert calls["change_bind"] == []  # nothing committed yet — still editing


def test_bind_edit_buffers_printable_chars():
    """While in bind-edit mode printable chars append to the buffer (routed away from actions)."""
    ui, calls = _make_ui()
    ui.dispatch("b")
    for ch in "0.0.0.0:8100":
        ui.dispatch(ch)
    assert ui.input_buffer == "0.0.0.0:8100"
    # the buffered chars must NOT have fired any action (e.g. the '.' / digits / ':' are inert here)
    assert calls["set_verbosity"] == []
    assert calls["exit"] == []
    assert ui.view == "log"


def test_bind_edit_backspace_deletes_last_char():
    """Backspace (\\x08 or \\x7f) deletes the last buffered char in bind-edit mode."""
    ui, _ = _make_ui()
    ui.dispatch("b")
    for ch in "127.0.0.1":
        ui.dispatch(ch)
    ui.dispatch("\x08")
    assert ui.input_buffer == "127.0.0."
    ui.dispatch("\x7f")
    assert ui.input_buffer == "127.0.0"


def test_bind_edit_enter_commits_valid_bind_and_exits():
    """Enter with a valid 'host:port' calls on_change_bind(host, port), logs 'restart required',
    and exits input mode (D-15d) — all via keystrokes, no input()."""
    ui, calls = _make_ui()
    ui.dispatch("b")
    for ch in "0.0.0.0:8100":
        ui.dispatch(ch)
    ui.dispatch("\r")
    assert calls["change_bind"] == [("0.0.0.0", 8100)]
    assert "restart required" in ui.log_lines[-1]
    assert ui.input_mode is None
    assert ui.input_buffer == ""


def test_bind_edit_enter_newline_variant_commits():
    """A '\\n' Enter variant also commits (some terminals deliver newline, not carriage return)."""
    ui, calls = _make_ui()
    ui.dispatch("b")
    for ch in "127.0.0.1:9000":
        ui.dispatch(ch)
    ui.dispatch("\n")
    assert calls["change_bind"] == [("127.0.0.1", 9000)]
    assert ui.input_mode is None


def test_bind_edit_esc_cancels_without_callback():
    """ESC cancels bind-edit: input_mode/buffer cleared and on_change_bind NOT called (D-15d)."""
    ui, calls = _make_ui()
    ui.dispatch("b")
    for ch in "0.0.0.0:8100":
        ui.dispatch(ch)
    ui.dispatch("\x1b")
    assert calls["change_bind"] == []
    assert ui.input_mode is None
    assert ui.input_buffer == ""


def test_bind_edit_invalid_buffer_does_not_call_callback():
    """Enter with an invalid buffer (bad/missing port) does NOT call on_change_bind."""
    ui, calls = _make_ui()
    ui.dispatch("b")
    for ch in "0.0.0.0:abc":
        ui.dispatch(ch)
    ui.dispatch("\r")
    assert calls["change_bind"] == []
    assert any("Invalid" in line for line in ui.log_lines)


def test_bind_edit_no_colon_is_invalid():
    """A buffer with no ':' separator is invalid (host:port required) — no callback."""
    ui, calls = _make_ui()
    ui.dispatch("b")
    for ch in "127.0.0.1":
        ui.dispatch(ch)
    ui.dispatch("\r")
    assert calls["change_bind"] == []


def test_bind_edit_header_shows_prompt():
    """While editing, the header surfaces an entry prompt with the current buffer (visible feedback).

    The bind-edit prompt REPLACES the help bar (r3) but the big banner, status and credits stay
    pinned — so the keystroke-driven change-bind editor never regresses and the operator still sees
    the banner + their live buffer at the same time.
    """
    ui, _ = _make_ui()
    ui.dispatch("b")
    for ch in "0.0.0.0":
        ui.dispatch(ch)
    out = _render_header_text(ui, width=80)
    assert "0.0.0.0" in out  # the live buffer is shown
    # a hint that we are in entry mode (host:port + how to confirm/cancel)
    assert "host:port" in out
    # the big banner stays pinned even while editing (r3 — banner is permanent, not transient)
    assert "█" in out


def test_bind_edit_ignores_special_key_sentinel():
    """An IGNORE_KEY (arrow/function) inside bind-edit mode is a no-op (does not corrupt the buffer)."""
    ui, _ = _make_ui()
    ui.dispatch("b")
    ui.dispatch("1")
    ui.dispatch(ConsoleUI.IGNORE_KEY)
    ui.dispatch("2")
    assert ui.input_buffer == "12"
    assert ui.input_mode == "bind"


# --- gap-closure r6: change-bind editor SHOWS the current bind as a read-only label -------
#   (UX correction of r5 — the editable buffer starts EMPTY, NOT pre-filled, so typing the new
#    value shows immediately; r5 pre-filled the buffer and the operator's typing "did nothing")


def test_b_starts_with_empty_buffer_even_with_get_bind():
    """With get_bind wired, 'b' enters bind-edit mode with an EMPTY buffer (NOT pre-filled, r6).

    r5 pre-filled the buffer with the current 'host:port' which confused the operator (typing
    appeared to do nothing). r6: the current bind is shown only as a read-only LABEL; the editable
    buffer starts empty so the typed value shows immediately.
    """
    ui, _ = _make_ui(get_bind=lambda: ("0.0.0.0", 8000))
    ui.dispatch("b")
    assert ui.input_mode == "bind"
    assert ui.input_buffer == ""  # EMPTY — not pre-filled with the current bind


def test_b_header_shows_current_bind_label_and_empty_new_field():
    """The bind-edit header LABELS the current bind (read-only) and shows the empty new-value field.

    The prompt must contain the word 'current' and the current 'host:port' text as a label, while
    the editable 'new:' field starts empty (typing shows there). The big banner stays pinned.
    """
    ui, _ = _make_ui(get_bind=lambda: ("0.0.0.0", 8000))
    ui.dispatch("b")
    out = _render_header_text(ui, width=120)
    # the current bind is surfaced as a read-only label
    assert "current" in out
    assert "0.0.0.0:8000" in out
    # the editable new-value field is present (empty so far) — the buffer drives it
    assert ui.input_buffer == ""
    # the big banner stays pinned even while editing (r3 — banner is permanent, not transient)
    assert "█" in out


def test_b_empty_buffer_typed_value_is_the_new_bind_and_enter_commits():
    """Typing into the (empty) buffer builds exactly the typed string; Enter commits that value.

    The buffer starts empty, so the typed '127.0.0.1:8080' IS the new bind (no clearing of a
    pre-fill). Enter calls on_change_bind('127.0.0.1', 8080) and pushes 'restart required'.
    """
    ui, calls = _make_ui(get_bind=lambda: ("0.0.0.0", 8000))
    ui.dispatch("b")
    assert ui.input_buffer == ""
    for ch in "127.0.0.1:8080":
        ui.dispatch(ch)
    assert ui.input_buffer == "127.0.0.1:8080"  # exactly the typed value, nothing prepended
    ui.dispatch("\r")
    assert calls["change_bind"] == [("127.0.0.1", 8080)]
    assert "restart required" in ui.log_lines[-1]
    assert ui.input_mode is None
    assert ui.input_buffer == ""


def test_b_esc_cancels_and_next_b_still_empty_with_fresh_current_label():
    """ESC cancels the editor (no callback, buffer empty); a later 'b' is still empty with a fresh
    current-bind label re-read from get_bind."""
    current = {"value": ("0.0.0.0", 8000)}
    ui, calls = _make_ui(get_bind=lambda: current["value"])
    ui.dispatch("b")
    ui.dispatch("9")  # type something so we can prove ESC clears it
    ui.dispatch("\x1b")  # ESC cancels
    assert calls["change_bind"] == []
    assert ui.input_mode is None
    assert ui.input_buffer == ""
    # the live bind changed between presses — the next 'b' label re-reads it fresh (buffer empty).
    current["value"] = ("127.0.0.1", 9000)
    ui.dispatch("b")
    assert ui.input_buffer == ""
    out = _render_header_text(ui, width=120)
    assert "127.0.0.1:9000" in out  # the LABEL reflects the live bind, re-read on each 'b'
    assert "current" in out


def test_b_without_get_bind_is_empty_buffer_no_current_label():
    """Backward-compat: a ConsoleUI WITHOUT get_bind (None) starts 'b' empty with NO current label."""
    ui, _ = _make_ui()  # _make_ui passes no get_bind → defaults to None
    assert ui.get_bind is None
    ui.dispatch("b")
    assert ui.input_mode == "bind"
    assert ui.input_buffer == ""  # empty buffer, no crash
    out = _render_header_text(ui, width=80)
    assert "host:port" in out  # generic prompt
    assert "current" not in out  # no current-bind label when get_bind is None


def test_b_current_label_with_markup_chars_renders_safely():
    """A current-bind value containing markup-ish chars renders the header label without raising."""
    # a (synthetic) host with markup-like chars exercises the round-4 escaping on the label path
    ui, _ = _make_ui(get_bind=lambda: ("[bold]h[/]", 8000))
    ui.dispatch("b")
    assert ui.input_buffer == ""  # buffer stays empty; only the LABEL carries the current bind
    out = _render_header_text(ui, width=120)  # must not raise MarkupError
    assert "8000" in out  # the current-bind label still renders verbatim
    assert "current" in out


def test_b_typed_value_with_markup_chars_renders_safely():
    """A typed buffer containing markup-ish chars renders the header without raising (markup-safe)."""
    ui, _ = _make_ui(get_bind=lambda: ("0.0.0.0", 8000))
    ui.dispatch("b")
    for ch in "[/]:80":
        ui.dispatch(ch)
    assert "[/]" in ui.input_buffer
    out = _render_header_text(ui, width=120)  # must not raise MarkupError
    assert "current" in out  # the label is still shown alongside the typed value


def test_get_bind_failure_degrades_to_no_current_label():
    """A get_bind that raises must not break edit mode — omit the label, keep the empty buffer."""

    def _boom():
        raise RuntimeError("bind unavailable")

    ui, _ = _make_ui(get_bind=_boom)
    ui.dispatch("b")
    assert ui.input_mode == "bind"
    assert ui.input_buffer == ""
    # the header still renders (falls back to the generic host:port prompt) without raising
    out = _render_header_text(ui, width=80)
    assert "host:port" in out
    assert "current" not in out  # the failing get_bind omits the current label


def test_cli_wires_get_bind_with_effective_host_port():
    """cli() passes get_bind=lambda: (effective_host, effective_port) to ConsoleUI (D-15d).

    Static source assertion (no run): the change-bind editor's current-bind LABEL must be wired to
    the RAW effective bind, NOT the browsable get_url mapping, so it shows the actual value in effect.
    """
    import inspect

    import backend.main as main_mod

    src = inspect.getsource(main_mod.cli)
    assert "get_bind=lambda: (effective_host, effective_port)" in src


# --- gap-closure r7: ipmideck entry point + `start` subcommand (additive) ----------------


def test_arg_parser_start_bare_and_flags_resolve_to_serve():
    """`start`, bare (no command), `serve`, and `--port` all resolve to the serve path (r7).

    The cli() dispatch only short-circuits on `reset-password` (and the flag early-returns); every
    other command — including the new `start` and a bare invocation — falls through to serve. We
    assert the parsed command is in {None, 'start', 'serve'} for each so `ipmideck start`,
    `ipmideck`, and `ipmideck --port 8080` all serve.
    """
    from backend.main import _build_arg_parser

    parser = _build_arg_parser()
    for argv in (["start"], [], ["serve"], ["--port", "8080"], ["--host", "127.0.0.1"]):
        args = parser.parse_args(argv)
        assert args.command in (None, "start", "serve"), f"{argv} did not resolve to the serve path"


def test_arg_parser_reset_password_resolves_to_reset():
    """`reset-password` parses to the reset-password command (the only short-circuit, unchanged)."""
    from backend.main import _build_arg_parser

    parser = _build_arg_parser()
    args = parser.parse_args(["reset-password"])
    assert args.command == "reset-password"


def test_arg_parser_start_with_flags_keeps_host_port():
    """`--host 127.0.0.1 --port 8080 start` carries the bind flags through (serve with flags).

    Global flags precede the subcommand (argparse convention — --host/--port are top-level options,
    same placement that already worked for `serve`). The flags resolve and the command still serves.
    """
    from backend.main import _build_arg_parser

    parser = _build_arg_parser()
    args = parser.parse_args(["--host", "127.0.0.1", "--port", "8080", "start"])
    assert args.command == "start"
    assert args.host == "127.0.0.1"
    assert args.port == 8080


def test_pyproject_declares_ipmideck_entry_point():
    """pyproject.toml [project.scripts] declares ipmideck → backend.main:cli (r7).

    `ipmideck` and `ipmideck start` serve once the operator re-runs `pip install -e .`.
    File-content assertion.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'ipmideck = "backend.main:cli"' in text


# --- gap-closure r7: change-bind persist failure must surface (not be silently swallowed) -


def test_cli_change_bind_callback_guards_persist_failure():
    """cli()'s _on_change_bind wraps update_server_yaml in try/except + logger.warning (r7).

    Static source assertion (no run — _on_change_bind is a closure nested in cli()/_serve_forever):
    a file-write failure (PermissionError/OSError) when persisting the new bind to config.yaml must
    NOT be silently swallowed. Previously the operator only saw "restart required" with no hint that
    the persist failed. The guard mirrors the existing _on_set_verbosity pattern (try/except +
    logger.warning) so a persist failure is logged (and, while Live owns the screen, shown in the
    body via the DequeLogHandler) instead of lost.
    """
    import inspect

    import backend.main as main_mod

    src = inspect.getsource(main_mod.cli)
    change_bind_idx = src.index("def _on_change_bind(")
    # the change-bind callback body must contain a try/except guarding the persist + a warning log.
    # Window the source from the def to the NEXT callback def so we assert against this body only.
    next_def_idx = src.index("\n        console = ", change_bind_idx)
    body = src[change_bind_idx:next_def_idx]
    assert "try:" in body, "_on_change_bind must guard update_server_yaml in try/except"
    assert "update_server_yaml(" in body
    assert "except Exception" in body, "_on_change_bind must catch persist failures"
    assert "logger.warning(" in body, "_on_change_bind must surface persist failure via logger.warning"


def test_restart_dispatch_calls_callback():
    """dispatch('r') invokes the on_restart callback (D-15c)."""
    ui, calls = _make_ui()
    ui.dispatch("r")
    assert calls["restart"] == [True]


def test_stop_sets_event_and_removes_handler():
    """stop() sets the stop event and removes an attached DequeLogHandler from the root logger."""
    from backend.console import DequeLogHandler

    ui, _ = _make_ui()
    handler = DequeLogHandler(deque(maxlen=10))
    logging.getLogger().addHandler(handler)
    ui._log_handler = handler
    try:
        ui.stop()
        assert ui._stop.is_set() is True
        assert handler not in logging.getLogger().handlers
        # idempotent: a second stop() must not raise
        ui.stop()
    finally:
        logging.getLogger().removeHandler(handler)


# --- gap-closure r7: suspend root StreamHandlers while Live owns the screen (flicker fix) -
#
# ROOT CAUSE of the host-UAT flicker / frame-breakdown: run() ADDED a DequeLogHandler to the root
# logger but did NOT remove the pre-existing StreamHandler (installed by logging.basicConfig() in
# lifespan). Every log record then went to BOTH handlers: the StreamHandler wrote straight to stderr
# — bypassing rich Live's redirect and fighting the screen frame (visible flicker) — and the frequent
# multi-line ERROR tracebacks (real-R720 polling failures) escaped the box → frame breakdown (raw
# logs outside the borders). The fix suspends the root StreamHandlers for the lifetime of Live so
# logging goes ONLY to the DequeLogHandler (rendered in the body), then restores them on exit.


def test_suspend_stream_handlers_removes_streamhandler_keeps_deque():
    """_suspend_stream_handlers() removes root StreamHandlers but leaves the DequeLogHandler attached.

    While Live owns the screen, the pre-existing stderr StreamHandler must be removed so log records
    do not bypass rich's redirect and fight the frame (the flicker bug). The DequeLogHandler — which
    feeds the on-screen body — must stay attached (it subclasses Handler, not StreamHandler, but the
    explicit guard keeps it safe regardless).
    """
    from backend.console import DequeLogHandler

    ui, _ = _make_ui()
    root = logging.getLogger()
    stream = logging.StreamHandler()
    deque_handler = DequeLogHandler(deque(maxlen=10))
    root.addHandler(stream)
    root.addHandler(deque_handler)
    try:
        saved = ui._suspend_stream_handlers()
        # the stderr StreamHandler was removed and captured for later restore
        assert stream in saved
        assert stream not in root.handlers
        # the DequeLogHandler is NOT suspended — it still feeds the on-screen body
        assert deque_handler not in saved
        assert deque_handler in root.handlers
        # restore re-adds exactly what was suspended
        ui._restore_stream_handlers(saved)
        assert stream in root.handlers
    finally:
        root.removeHandler(stream)
        root.removeHandler(deque_handler)


def test_suspend_stream_handlers_is_noop_with_zero_stream_handlers():
    """With no root StreamHandler attached, _suspend_stream_handlers() is a no-op (idempotent).

    Safe across restarts: run() is called per restart and each call removes+restores its own
    snapshot; a boot with zero stream handlers (e.g. handlers not yet installed) returns []
    and restore([]) does nothing.
    """
    ui, _ = _make_ui()
    root = logging.getLogger()
    # snapshot + strip any handlers the test runner may have attached so this is deterministic
    pre_existing = [h for h in root.handlers if isinstance(h, logging.StreamHandler)]
    for h in pre_existing:
        root.removeHandler(h)
    try:
        saved = ui._suspend_stream_handlers()
        assert saved == []
        # restore of an empty snapshot must not raise and must not add anything
        before = list(root.handlers)
        ui._restore_stream_handlers(saved)
        assert list(root.handlers) == before
    finally:
        for h in pre_existing:
            root.addHandler(h)


def test_run_suspends_and_restores_stream_handlers(monkeypatch):
    """run() suspends root StreamHandlers while Live is active and restores them in finally.

    End-to-end (no real Live/TTY): a dummy stderr StreamHandler is attached to the root logger; run()
    must remove it for the duration of the (stubbed) Live block and re-add it on exit. We capture the
    root handler set from INSIDE the render loop to prove the StreamHandler is gone while Live owns
    the screen, and assert it is back after run() returns.
    """
    import backend.console as console_mod

    ui, _ = _make_ui()
    root = logging.getLogger()
    stream = logging.StreamHandler()
    root.addHandler(stream)

    # Force the interactive gate True so run() proceeds (no real TTY in CI).
    monkeypatch.setattr(console_mod, "is_interactive", lambda: True)

    # Stub rich Console + Live so run() touches no real screen.
    import rich.console as _rich_console
    import rich.live as _rich_live

    class _FakeLive:
        def __init__(self, *_a, **_k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(_rich_console, "Console", lambda *_a, **_k: object())
    monkeypatch.setattr(_rich_live, "Live", _FakeLive)

    # Stub the layout writes (object() renderables would choke a real Layout).
    class _FakeLayout(dict):
        def __getitem__(self, _k):
            class _Region:
                def update(self, _v):
                    pass

            return _Region()

    monkeypatch.setattr(ui, "layout", _FakeLayout())
    monkeypatch.setattr(ui, "render_header", lambda: object())

    handlers_during_live: list = []

    def _capture_then_stop():
        # capture the live root-handler set, then end the loop deterministically
        handlers_during_live.extend(root.handlers)
        ui._stop.set()
        return object()

    monkeypatch.setattr(ui, "render_body", _capture_then_stop)

    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda _s: None)

    try:
        ui.run()
        # WHILE Live owned the screen the stderr StreamHandler was suspended (only the deque feeds)
        assert stream not in handlers_during_live, "StreamHandler not suspended during Live (flicker)"
        # AFTER run() returns it is restored so normal stderr logging resumes
        assert stream in root.handlers, "StreamHandler not restored after run() (logging lost)"
    finally:
        root.removeHandler(stream)


# --- 04.1-04 gap-closure r3: big banner PINNED in header, nothing clips (concern 1) ------


def test_header_shows_big_banner_and_help_bar_at_80_and_120_cols():
    """The pinned header shows the BIG ANSI Shadow banner AND the full help bar at 80 AND 120 cols.

    r3 user override of D-02 "poi compatto": the big banner is no longer a transient splash — it is
    PERMANENTLY pinned in the header with the help bar below it. Both must be present and nothing
    may clip at EITHER width. The banner is detected by its ANSI Shadow block glyph ('█'); the help
    bar by its literal key hints '[v]'/'[q]' (bracket-escaped so they render verbatim) and labels.
    """
    ui, _ = _make_ui()
    for width in (80, 120):
        out = _render_header_text(ui, width=width)
        # (a) the big banner art is present — a run of ANSI Shadow block chars
        assert "█" in out, f"banner block art missing at {width} cols"
        # (b) the help/shortcut bar is present and complete
        assert "[v]" in out, f"[v] hint missing at {width} cols"
        assert "verbosity" in out, f"verbosity label missing at {width} cols"
        assert "[q]" in out, f"[q] hint missing at {width} cols"
        # (c) the status line and credits are present (not clipped off the bottom)
        assert "INFO" in out, f"verbosity status missing at {width} cols"
        assert "Clients" in out, f"client count label missing at {width} cols"
        assert "Luigi Tanzillo" in out, f"credits author missing at {width} cols"


def test_header_size_reserves_banner_plus_overhead():
    """HEADER_SIZE must reserve at least the big banner's line count + the layout overhead.

    Sized from the ACTUAL banner height (so it auto-adapts when APP_NAME changes in 04.2), not a
    hardcoded guess: HEADER_SIZE == banner rows + _HEADER_OVERHEAD (blank + up-to-2 wrapped
    help-bar rows + status + credits + 2 panel borders). The reserved rows must be >= the banner
    line count plus that overhead so the banner + help bar + status + credits never clip.
    """
    from backend.console import _HEADER_OVERHEAD, _banner_line_count

    banner_rows = _banner_line_count()
    assert banner_rows >= 1
    assert ConsoleUI.HEADER_SIZE >= banner_rows + _HEADER_OVERHEAD


def test_header_fits_region_size_at_80_and_120_cols():
    """The rendered header (incl. panel border rows) must fit HEADER_SIZE at 80 AND 120 cols.

    The rendered panel height must be <= HEADER_SIZE so the body region (logs) is never pushed
    off-screen — at 80 cols the help bar wraps to 2 rows, at 120 cols it fits on one; both fit.
    """
    ui, _ = _make_ui()
    for width in (80, 120):
        out = _render_header_text(ui, width=width)
        rendered_rows = len(out.rstrip("\n").splitlines())
        assert rendered_rows <= ConsoleUI.HEADER_SIZE, f"header overflowed HEADER_SIZE at {width}"


def test_header_help_bar_degrades_on_narrow_terminal():
    """On a narrow (40-col) terminal the header still renders without crashing (graceful wrap).

    The big banner art (block glyphs) and at least one help-bar key hint survive even when the
    content must wrap — render_header() never raises and the banner is still present.
    """
    ui, _ = _make_ui()
    out = _render_header_text(ui, width=40)
    assert "█" in out  # the big banner block art still renders
    assert "verbosity" in out  # at least one help-bar label survives the wrap


# --- 04.1-04 gap-closure: special-key 2-byte consumption (concern 2) ---------------------


def test_read_key_consumes_windows_special_key_prefix(monkeypatch):
    """read_key() consumes the Windows '\\xe0'/'\\x00' prefix + scan code as ONE ignorable event.

    On Windows msvcrt.getwch() returns '\\xe0' (or '\\x00') then the scan code for arrow/function/
    nav keys (e.g. '\\xe0' then 'P' = Down arrow). The two getwch() calls must be consumed together
    and yield the IGNORE sentinel, not two stray key events.
    """
    import backend.console as console_mod

    # Force the win32 branch and feed a fake msvcrt whose getwch() yields the Down-arrow sequence.
    monkeypatch.setattr(console_mod.sys, "platform", "win32")
    seq = iter(["\xe0", "P"])

    class _FakeMsvcrt:
        @staticmethod
        def getwch():
            return next(seq)

    monkeypatch.setitem(__import__("sys").modules, "msvcrt", _FakeMsvcrt)
    result = console_mod.read_key()
    assert result == ConsoleUI.IGNORE_KEY
    # both bytes were consumed — the scan code 'P' must NOT leak out as a second event
    import pytest

    with pytest.raises(StopIteration):
        next(seq)


def test_read_key_returns_plain_char_on_windows(monkeypatch):
    """A normal printable key on Windows is returned verbatim (no prefix consumption)."""
    import backend.console as console_mod

    monkeypatch.setattr(console_mod.sys, "platform", "win32")

    class _FakeMsvcrt:
        @staticmethod
        def getwch():
            return "c"

    monkeypatch.setitem(__import__("sys").modules, "msvcrt", _FakeMsvcrt)
    assert console_mod.read_key() == "c"


def test_dispatch_ignores_special_key_sentinel():
    """dispatch(IGNORE_KEY) is a no-op: the view does not change and no callback fires."""
    ui, calls = _make_ui()
    ui.view = "log"
    ui.dispatch(ConsoleUI.IGNORE_KEY)
    assert ui.view == "log"
    assert calls["exit"] == []
    assert calls["set_verbosity"] == []
    assert calls["restart"] == []


def test_dispatch_ignores_none():
    """dispatch(None) is a no-op (defensive — a backend that returns None must not crash dispatch)."""
    ui, calls = _make_ui()
    ui.dispatch(None)
    assert ui.view == "log"
    assert calls["exit"] == []


# --- 04.1-04 gap-closure: visible last-key feedback (concern 3) --------------------------


def test_last_key_updates_on_actionable_dispatch():
    """An actionable keypress updates last_key and the header status reflects it (visible feedback)."""
    ui, _ = _make_ui()
    ui.dispatch("u")  # show-URL — actionable
    assert ui.last_key == "u"
    out = _render_header_text(ui, width=80)
    assert "last" in out  # the status line carries a 'last:' indicator
    assert "u" in out


def test_last_key_not_set_by_ignored_special_key():
    """The ignore sentinel must NOT overwrite last_key with a misleading actionable value."""
    ui, _ = _make_ui()
    ui.dispatch("v")  # actionable -> last_key == 'v'
    assert ui.last_key == "v"
    ui.dispatch(ConsoleUI.IGNORE_KEY)  # ignored -> last_key unchanged
    assert ui.last_key == "v"


# --- gap-closure r3: big banner pinned in header → transient TTY splash + dwell removed ---


def test_no_transient_splash_constant_remains():
    """The SPLASH_SECONDS dwell constant is GONE — the banner is now pinned in the header (r3).

    The big banner lives permanently in the console header, so there is no pre-Live splash to dwell
    on; the now-redundant SPLASH_SECONDS constant must not linger as dead config.
    """
    import backend.main as main_mod

    assert not hasattr(main_mod, "SPLASH_SECONDS")


def test_tty_path_has_no_splash_print_or_dwell_but_keeps_gate():
    """The interactive (TTY) branch no longer prints a transient splash or sleeps, but STILL sets
    the host_splash_shown gate so lifespan (D-21) does not double-print the banner.

    r3 moved the big banner into the pinned header, so the flash-then-disappear pre-Live splash and
    its dwell were removed. We assert statically (no actual run): the TTY branch sets the gate, the
    redundant splash print / dwell are absent, and the render thread still starts.
    """
    import inspect

    import backend.main as main_mod

    src = inspect.getsource(main_mod.cli)
    # the transient pre-Live splash print and the dwell must be GONE (banner is in the header now)
    assert "print_banner_safe(banner())" not in src
    assert "time.sleep(SPLASH_SECONDS)" not in src
    assert "SPLASH_SECONDS" not in src
    # the gate is STILL set on the TTY path so lifespan (D-21) does not double-print the banner,
    # and the render thread (which renders the header-pinned banner) still starts after it.
    interactive_idx = src.index("if interactive:")
    gate_idx = src.index("app.state.host_splash_shown = True")
    render_idx = src.index("render_thread = threading.Thread")
    assert interactive_idx < gate_idx < render_idx


def test_lifespan_still_emits_banner_to_logs_when_gate_unset():
    """D-21 preserved: lifespan still emits the banner ONCE to logs on the non-TTY/Docker path.

    The gate (host_splash_shown) is set ONLY on the interactive TTY path; when it is unset
    (Docker/piped) lifespan must still print the branded banner so `docker logs` captures it. We
    assert the lifespan source keeps the gated print_banner_safe(render_banner_safe()) emission.
    """
    import inspect

    import backend.main as main_mod

    src = inspect.getsource(main_mod.lifespan)
    assert 'getattr(app.state, "host_splash_shown", False)' in src
    assert "print_banner_safe(render_banner_safe())" in src


# --- 04.1-04 gap-closure r4: markup-safe rendering (the console-freeze regression) -------
#
# ROOT CAUSE of the host-UAT freeze: render_body() built the log view as
# Panel("\n".join(self.log_lines)) — rich parses that string as CONSOLE MARKUP by default. A log
# line containing markup-like text (an unmatched '[/]', a mismatched '[/italic]', any '[tag]') makes
# rich raise rich.errors.MarkupError at RENDER time, inside the while-loop under Live(screen=True).
# The exception propagates out of the render thread → the Live screen freezes and never re-renders
# (the header 'last:' indicator stays frozen, "nothing shows"). Same hazard for table cells (an odd
# session IP / User-Agent / hostname) and the bind-edit buffer (arbitrary typed chars). The fix
# renders ALL arbitrary text as PLAIN rich Text, so markup is never parsed and the render can never
# crash. These tests LOCK that: each renders the offending content WITHOUT raising.


def test_render_body_log_view_survives_markup_like_lines():
    """render_body (log view) with markup-like log lines renders WITHOUT raising (freeze lock).

    A bare '[/]', a mismatched '[/italic]', an unclosed '[' and a Python list repr would each make
    rich raise MarkupError if the log body were parsed as markup. Rendered as plain Text they are
    inert — this is the direct regression lock for the host-UAT console freeze.
    """
    ui, _ = _make_ui()
    for line in (
        "client [bold]X[/] connected",
        "[/]",
        "mismatch [bold]x[/italic]",
        "unclosed [",
        "params=['a', 'b']",
        "[/notopen]",
    ):
        ui.log_lines.append(line)
    out = _render_body_text(ui, width=80)
    # the literal text survives (rendered verbatim, not eaten as markup)
    assert "[/]" in out
    assert "unclosed [" in out
    assert "params=['a', 'b']" in out


def test_render_body_sessions_view_survives_markup_in_cells():
    """render_body (sessions view) with a session whose IP/User-Agent contains '[' renders safely."""
    ws = _FakeWSManager(
        sessions_data=[
            {
                "ip": "[/]",
                "connected_since": "2026-06-16T00:00:00Z",
                "user_agent": "Mozilla [bold]X[/] /5.0",
            }
        ]
    )
    ui, _ = _make_ui(ws_manager=ws)
    ui.view = "sessions"
    out = _render_body_text(ui, width=120)
    assert "[/]" in out  # the odd IP renders verbatim, no MarkupError


def test_render_body_servers_view_survives_markup_in_cells():
    """render_body (servers view) with a hostname containing '[' renders without raising."""
    ui, _ = _make_ui(
        get_servers=lambda: [{"name": "srv-[/]", "host": "host[bold]", "status": "online"}]
    )
    ui.view = "servers"
    out = _render_body_text(ui, width=120)
    assert "srv-[/]" in out  # the odd name renders verbatim


def test_render_header_bind_buffer_survives_markup_chars():
    """Typing markup-like chars ('[', '[/]') into the bind buffer does not crash the header render."""
    ui, _ = _make_ui()
    ui.dispatch("b")
    for ch in "[/]:80":
        ui.dispatch(ch)
    # the buffer holds the raw chars and the header still renders without raising
    assert "[/]" in ui.input_buffer
    out = _render_header_text(ui, width=80)
    assert "host:port" in out  # still in the bind-entry prompt, render succeeded


# --- 04.1-04 gap-closure r4: resilient render loop (a bad frame must NOT kill the loop) ---


def test_run_loop_survives_a_render_exception(monkeypatch):
    """A single render exception is caught and the run() loop keeps going (never freezes again).

    Belt-and-suspenders: even if some future renderable raises, the per-frame render is guarded so
    the render thread can never die from a bad frame. We monkeypatch render_body to raise on the
    FIRST call then succeed, force the TTY gate + stub Live/Console so no real screen is touched,
    and assert the loop ran MORE than once (it survived the raise) and stop() cleaned up.
    """
    import backend.console as console_mod

    ui, _ = _make_ui()

    # Force the interactive gate True so run() proceeds (no real TTY in CI).
    monkeypatch.setattr(console_mod, "is_interactive", lambda: True)

    # Stub rich Console + Live so run() touches no real screen. run() imports them locally
    # (`from rich.console import Console` / `from rich.live import Live`), so patch the source
    # modules directly — that is what the local import resolves to.
    import rich.console as _rich_console
    import rich.live as _rich_live

    class _FakeLive:
        def __init__(self, *_a, **_k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(_rich_console, "Console", lambda *_a, **_k: object())
    monkeypatch.setattr(_rich_live, "Live", _FakeLive)

    calls = {"render_header": 0, "render_body": 0}
    real_stop = ui._stop

    def _fake_header():
        calls["render_header"] += 1
        return object()

    def _fake_body():
        calls["render_body"] += 1
        if calls["render_body"] == 1:
            raise ValueError("simulated bad frame — must NOT kill the loop")
        # after surviving the first bad frame, signal stop so the test is deterministic+fast
        real_stop.set()
        return object()

    # The Layout.update path would choke on our object() stubs; stub the layout writes too.
    class _FakeLayout(dict):
        def __getitem__(self, _k):
            class _Region:
                def update(self, _v):
                    pass

            return _Region()

    monkeypatch.setattr(ui, "layout", _FakeLayout())
    monkeypatch.setattr(ui, "render_header", _fake_header)
    monkeypatch.setattr(ui, "render_body", _fake_body)
    # run() does `import time` locally, so patch the stdlib module's sleep to be instant — the
    # loop stays fast and deterministic (the stop event is what actually ends it, not the sleep).
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda _s: None)

    ui.run()  # must return normally (loop survived the raise, then stop() ended it)

    # render_body was called at least twice: the raising frame + the surviving frame.
    assert calls["render_body"] >= 2, "render loop did not survive the bad frame (froze)"
    assert ui._stop.is_set() is True  # stop() ran in finally → handler removed, clean teardown


# --- 04.1-04 gap-closure r4: initial verbosity actually applied on the interactive path ---


def test_interactive_startup_applies_initial_verbosity_and_suppresses_noise():
    """The interactive (TTY) startup path applies the initial level AND tames noisy loggers (D-04).

    The status showed 'Verbosity: INFO' but DEBUG aiosqlite/uvicorn spam still flooded the body —
    the displayed level was never enforced on the console path. We assert (statically, no run) that
    cli()'s interactive branch calls apply_log_level(<initial level>) + suppress_noisy_loggers()
    BEFORE the render thread starts, so INFO is real and the flood is tamed at baseline.
    """
    import inspect

    import backend.main as main_mod

    src = inspect.getsource(main_mod.cli)
    interactive_idx = src.index("if interactive:")
    apply_idx = src.index("apply_log_level(", interactive_idx)
    suppress_idx = src.index("suppress_noisy_loggers(", interactive_idx)
    render_idx = src.index("render_thread = threading.Thread", interactive_idx)
    # both are applied on the interactive path BEFORE the render loop starts
    assert interactive_idx < apply_idx < render_idx
    assert interactive_idx < suppress_idx < render_idx


# --- 04.1-04 gap-closure r8: readable timestamp + colour-coded level token (markup-safe) ---
#
# The on-screen log body showed plain lines like
#   2026-06-16 05:22:16,816 INFO ipmideck: <message>
# rendered as a single markup-safe Text (r4). User requests for r8:
#   (1) make the timestamp readable — show only HH:MM:SS (no date, no ',mmm' millis), and
#   (2) colour-code the level token (INFO/WARNING/ERROR/…) and make action-result messages like
#       "restart required" stand out.
# The fix keeps the r4 markup-safety guarantee: DequeLogHandler now stores a rich Text built from
# per-part STYLE SPANS (.append(part, style=...)) — never a '[markup]' string — so arbitrary log
# content (brackets in object reprs / BMC output / SQL) can still NEVER trip rich's markup parser.
# render_body() joins the Text entries (coercing any stray str defensively) into one renderable.


def _emit_record(handler, level, msg, name="ipmideck.modules.sensors", exc_info=None):
    """Build + emit a LogRecord through a handler and return the stored deque entry."""
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )
    handler.emit(record)
    return handler.log_lines[-1]


def _span_style_for(text_obj, substring):
    """Return the style of the FIRST Text span that covers `substring` (or None)."""
    from rich.text import Text

    assert isinstance(text_obj, Text)
    plain = text_obj.plain
    start = plain.index(substring)
    end = start + len(substring)
    for span in text_obj.spans:
        if span.start <= start and span.end >= end:
            return str(span.style)
    return None


def test_deque_handler_stores_text_with_readable_time_and_fields():
    """DequeLogHandler.emit stores a rich Text whose plain text has HH:MM:SS (no date/millis),
    the level name, the logger name and the message — readable timestamp + structured fields (r8)."""
    import re

    from rich.text import Text

    from backend.console import DequeLogHandler

    handler = DequeLogHandler(deque(maxlen=10))
    entry = _emit_record(handler, logging.INFO, "sensor poll ok", name="ipmideck.modules.sensors")
    assert isinstance(entry, Text)
    plain = entry.plain
    # HH:MM:SS present, and NO date / no comma-millis (the readable-time ask)
    assert re.search(r"\b\d{2}:\d{2}:\d{2}\b", plain), f"no HH:MM:SS in {plain!r}"
    assert re.search(r"\d{4}-\d{2}-\d{2}", plain) is None, f"date leaked into {plain!r}"
    assert "," not in plain.split(" ", 1)[0], f"millis leaked into the time token in {plain!r}"
    # the structured fields are all present
    assert "INFO" in plain
    assert "ipmideck.modules.sensors" in plain
    assert "sensor poll ok" in plain


def test_deque_handler_colours_level_token_by_severity():
    """The level token carries the LEVEL_STYLES colour per severity; timestamp + logger name dim (r8).

    Colour JUST the level token (the user: 'solo alla scritta info o altro'). The timestamp and the
    logger name are de-emphasised (dim); the message itself stays default (no style)."""
    from backend.console import LEVEL_STYLES, DequeLogHandler

    handler = DequeLogHandler(deque(maxlen=10))

    info = _emit_record(handler, logging.INFO, "ok")
    assert LEVEL_STYLES["INFO"] in _span_style_for(info, "INFO")

    warn = _emit_record(handler, logging.WARNING, "careful")
    assert LEVEL_STYLES["WARNING"] in _span_style_for(warn, "WARNING")

    err = _emit_record(handler, logging.ERROR, "boom")
    assert LEVEL_STYLES["ERROR"] in _span_style_for(err, "ERROR")

    dbg = _emit_record(handler, logging.DEBUG, "trace")
    assert LEVEL_STYLES["DEBUG"] in _span_style_for(dbg, "DEBUG")

    crit = _emit_record(handler, logging.CRITICAL, "fatal")
    assert LEVEL_STYLES["CRITICAL"] in _span_style_for(crit, "CRITICAL")


def test_level_styles_table_has_expected_severities():
    """LEVEL_STYLES is a module-level dict mapping each severity to its colour (r8)."""
    from backend.console import LEVEL_STYLES

    assert LEVEL_STYLES["DEBUG"] == "dim cyan"
    assert LEVEL_STYLES["INFO"] == "green"
    assert LEVEL_STYLES["WARNING"] == "yellow"
    assert LEVEL_STYLES["ERROR"] == "bold red"
    assert LEVEL_STYLES["CRITICAL"] == "bold white on red"


def test_deque_handler_dims_time_and_logger_name():
    """The timestamp and the logger name are rendered dim (de-emphasised chrome), message default."""
    from backend.console import DequeLogHandler

    handler = DequeLogHandler(deque(maxlen=10))
    entry = _emit_record(handler, logging.INFO, "hello world", name="ipmideck.console")
    # the logger name span is dim
    assert "dim" in (_span_style_for(entry, "ipmideck.console") or "")
    # the message carries no styling span (default)
    assert _span_style_for(entry, "hello world") in (None, "", "none")


def test_deque_handler_record_with_markup_message_does_not_raise():
    """A record whose message contains markup-like brackets is stored AND rendered without raising.

    Markup-safety regression lock (r4 preserved through r8): the Text is built from STYLE SPANS via
    .append(), never a '[markup]' string, so brackets in the message are literal and inert."""
    from rich.console import Console
    from rich.text import Text

    from backend.console import DequeLogHandler

    handler = DequeLogHandler(deque(maxlen=10))
    entry = _emit_record(handler, logging.ERROR, "client [bold]X[/] failed [/notopen]")
    assert isinstance(entry, Text)
    assert "[bold]X[/]" in entry.plain  # the brackets survive verbatim
    # rendering the Text must not raise MarkupError (it is not parsed as markup)
    console = Console(width=80, record=True)
    console.print(entry)
    assert "[/notopen]" in console.export_text()


def test_deque_handler_renders_exc_info_traceback_in_body():
    """A record carrying exc_info renders its multi-line traceback in the body without raising (r8)."""
    from rich.console import Console
    from rich.text import Text

    from backend.console import DequeLogHandler

    handler = DequeLogHandler(deque(maxlen=10))
    try:
        raise ValueError("kaboom")
    except ValueError:
        import sys

        exc = sys.exc_info()
    entry = _emit_record(handler, logging.ERROR, "poll failed", exc_info=exc)
    assert isinstance(entry, Text)
    plain = entry.plain
    assert "poll failed" in plain
    # the traceback text is appended after the message (multi-line) and renders without raising
    assert "Traceback" in plain
    assert "ValueError" in plain
    console = Console(width=120, record=True)
    console.print(entry)
    assert "kaboom" in console.export_text()


def test_push_log_accepts_style_and_stores_styled_text():
    """_push_log(line, style=...) stores a rich Text carrying that style; default style is neutral."""
    from rich.text import Text

    ui, _ = _make_ui()
    ui._push_log("plain default line")
    default_entry = ui.log_lines[-1]
    assert isinstance(default_entry, Text)
    assert default_entry.plain == "plain default line"

    ui._push_log("Bind set to h:1 — restart required to apply (press r)", style="bold green")
    styled = ui.log_lines[-1]
    assert isinstance(styled, Text)
    assert "bold green" in _span_style_for(styled, "restart required")


def test_change_bind_commit_uses_prominent_style():
    """The change-bind success 'restart required' line is stored in a PROMINENT style (user's ask)."""
    ui, calls = _make_ui()
    ui.dispatch("b")
    for ch in "0.0.0.0:8100":
        ui.dispatch(ch)
    ui.dispatch("\r")
    assert calls["change_bind"] == [("0.0.0.0", 8100)]
    entry = ui.log_lines[-1]
    assert "restart required" in entry.plain
    # the whole confirmation is a prominent (bold green) span
    assert "bold green" in _span_style_for(entry, "restart required")


def test_invalid_bind_is_red():
    """An invalid host/port confirmation is stored in red so the operator sees the rejection (r8)."""
    ui, calls = _make_ui()
    ui.dispatch("b")
    for ch in "0.0.0.0:abc":
        ui.dispatch(ch)
    ui.dispatch("\r")
    assert calls["change_bind"] == []
    entry = ui.log_lines[-1]
    assert "Invalid" in entry.plain
    assert "red" in _span_style_for(entry, "Invalid")


def test_url_line_is_cyan():
    """The 'u' show-URL line is stored cyan so the address stands out from ordinary log noise (r8)."""
    ui, _ = _make_ui(get_url=lambda: "http://127.0.0.1:8099")
    ui.dispatch("u")
    entry = ui.log_lines[-1]
    assert entry.plain == "http://127.0.0.1:8099"
    assert "cyan" in _span_style_for(entry, "http://127.0.0.1:8099")


def test_update_stub_line_is_default_or_dim():
    """The 'g' update-stub line is neutral (default/dim) — informational, not an alert (r8)."""
    from rich.text import Text

    ui, _ = _make_ui()
    ui.dispatch("g")
    entry = ui.log_lines[-1]
    assert isinstance(entry, Text)
    assert VERSION in entry.plain
    style = _span_style_for(entry, VERSION)
    assert style in (None, "", "none") or "dim" in style


def test_render_body_log_view_joins_text_entries_single_renderable():
    """render_body (log view) joins the deque Text entries into a SINGLE renderable, no raise (r8)."""
    ui, _ = _make_ui()
    ui.dispatch("u")  # a styled Text entry
    ui.dispatch("g")  # another entry
    out = _render_body_text(ui, width=80)
    assert "http://h:3000" in out
    assert VERSION in out


def test_render_body_log_view_coerces_stray_str_entries():
    """A mixed deque (Text + a defensively-stored str) still renders without raising (r8 coercion).

    Older callers / a future regression could push a raw str; render_body must coerce it to Text so
    the join never raises on a mixed deque."""
    ui, _ = _make_ui()
    # a raw str pushed directly (bypassing _push_log) and a styled Text entry
    ui.log_lines.append("a raw string entry [/]")  # stray str with markup-like chars
    ui.dispatch("u")  # styled Text
    out = _render_body_text(ui, width=80)
    assert "a raw string entry [/]" in out  # the stray str renders verbatim (coerced, not parsed)
    assert "http://h:3000" in out


def test_render_body_log_view_handler_text_with_markup_message_renders():
    """A handler-stored Text whose message has markup chars renders in the body view without raising."""
    from backend.console import DequeLogHandler

    ui, _ = _make_ui()
    handler = DequeLogHandler(ui.log_lines)
    _emit_record(handler, logging.ERROR, "boom [bold]x[/] [/notopen]")
    out = _render_body_text(ui, width=80)
    assert "[/notopen]" in out  # the level-coloured line renders verbatim, no MarkupError


# --- 04.1-04 gap-closure r10: action results switch back to the log view so they are visible ---
#
# ROOT CAUSE (concern 2): pressing 'u' (URL), 'g' (update stub), or committing a change-bind pushed
# a line into the log deque but did NOT switch the view. While the operator is in the 's' (servers)
# or 'c' (sessions) sub-view, the body shows the TABLE — so the freshly pushed line is HIDDEN behind
# it ("I pressed u and nothing happened"). The fix adds a _show_log() helper that pushes the line AND
# flips view back to "log" so the result is always visible. Used by 'u', 'g', and BOTH _commit_bind
# branches. 'c'/'s' still open their sub-views; 'q'/ESC still return to log. Idempotent on log view.


def test_show_log_pushes_line_and_switches_to_log_view():
    """_show_log(line) pushes the line into the deque AND flips the view back to 'log'."""
    ui, _ = _make_ui()
    ui.view = "servers"
    ui._show_log("hello result")
    assert ui.view == "log"
    assert ui.log_lines[-1].plain == "hello result"


def test_show_log_carries_style():
    """_show_log(line, style=...) stores the styled Text (same styling contract as _push_log)."""
    ui, _ = _make_ui()
    ui.view = "sessions"
    ui._show_log("Bind set to h:1 — restart required to apply (press r)", style="bold green")
    assert ui.view == "log"
    assert "bold green" in _span_style_for(ui.log_lines[-1], "restart required")


def test_show_log_idempotent_when_already_on_log_view():
    """_show_log() on the log view leaves the view 'log' and still pushes (no toggle/regression)."""
    ui, _ = _make_ui()
    assert ui.view == "log"
    ui._show_log("already here")
    assert ui.view == "log"
    assert ui.log_lines[-1].plain == "already here"


def test_url_from_servers_view_switches_back_to_log():
    """dispatch('u') while in the servers sub-view switches to log so the URL is visible (r10)."""
    from rich.text import Text

    ui, _ = _make_ui(get_url=lambda: "http://127.0.0.1:8099")
    ui.view = "servers"
    ui.dispatch("u")
    assert ui.view == "log"  # switched back so the pushed URL is not hidden behind the table
    last = ui.log_lines[-1]
    assert isinstance(last, Text)
    assert last.plain == "http://127.0.0.1:8099"


def test_update_stub_from_sessions_view_switches_back_to_log():
    """dispatch('g') while in the sessions sub-view switches to log so the stub line is visible (r10)."""
    ui, _ = _make_ui()
    ui.view = "sessions"
    ui.dispatch("g")
    assert ui.view == "log"
    assert VERSION in ui.log_lines[-1]


def test_commit_bind_invalid_from_servers_view_switches_back_to_log():
    """An invalid bind committed from the servers sub-view switches to log + shows the red error (r10)."""
    ui, calls = _make_ui()
    ui.view = "servers"
    ui.dispatch("b")  # bind editor REPLACES the action map but view stays 'servers' underneath
    for ch in "0.0.0.0:abc":
        ui.dispatch(ch)
    ui.dispatch("\r")  # commit invalid
    assert calls["change_bind"] == []
    assert ui.view == "log"  # the invalid message is now visible, not hidden behind the table
    entry = ui.log_lines[-1]
    assert "Invalid" in entry.plain
    assert "red" in _span_style_for(entry, "Invalid")


def test_commit_bind_valid_from_sessions_view_switches_back_to_log():
    """A valid bind committed from the sessions sub-view switches to log, calls the callback, shows green."""
    ui, calls = _make_ui()
    ui.view = "sessions"
    ui.dispatch("b")
    for ch in "127.0.0.1:8081":
        ui.dispatch(ch)
    ui.dispatch("\r")  # commit valid
    assert calls["change_bind"] == [("127.0.0.1", 8081)]
    assert ui.view == "log"  # the 'restart required' confirmation is visible, not behind the table
    entry = ui.log_lines[-1]
    assert "restart required" in entry.plain
    assert "bold green" in _span_style_for(entry, "restart required")


def test_sub_view_keys_still_open_their_views():
    """'c' and 's' still open their sub-views (the _show_log fix must not break sub-view entry, r10)."""
    ui, _ = _make_ui()
    ui.dispatch("c")
    assert ui.view == "sessions"
    ui.dispatch("\x1b")  # ESC back to log
    assert ui.view == "log"
    ui.dispatch("s")
    assert ui.view == "servers"
    ui.dispatch("q")  # q back to log
    assert ui.view == "log"


# --- console-logs-tail-overflow: the Logs body must TAIL to the visible region (newest on screen) ---
#
# ROOT CAUSE: render_body()'s log branch joined ALL deque entries into one Text and let the rich
# Layout "body" region crop the overflow. rich crops region overflow AT THE BOTTOM, so on a SHORT
# terminal the NEWEST lines — the dashboard URL pushed by 'u', and recent logs — were exactly what
# got clipped and never shown (the operator "loses" the URL). The fix tails the log body to the
# visible body-region height (console height − HEADER_SIZE − the Logs Panel's 2 border rows) using a
# physical-row tail, so the last appended line is ALWAYS visible — even if a single line wraps to more
# rows than fit (it then shows its tail, not its head).


def _render_body_at_size(ui, width: int, height: int) -> str:
    """Render ui.render_body() inside a header+body Layout at a FIXED console size and return plain text.

    This mirrors exactly what run() does each Live frame: a fixed-size pinned header region above a
    flexing body region whose content is render_body(). The console size is pinned so the
    bottom-clipping (and the tail fix) are deterministic regardless of the runner's real terminal.
    The same Console is wired to ui._console so render_body() can size its tail to this region.
    """
    from rich.console import Console
    from rich.layout import Layout

    console = Console(width=width, height=height, record=True)
    ui._console = console
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=ConsoleUI.HEADER_SIZE),
        Layout(name="body"),
    )
    layout["body"].update(ui.render_body())
    console.print(layout, height=height)
    return console.export_text()


def test_log_body_tails_newest_line_into_view_on_short_terminal():
    """On a SHORT terminal the NEWEST log line (the URL) is visible; an OLD beyond-window line is not.

    Append far more entries than fit the body region (100 lines), with a unique sentinel as the LAST
    entry (the 'u' URL) and a unique sentinel as an EARLY entry. Rendered through a small-height
    Console wired to ui._console, the tail must surface the newest sentinel and drop the oldest one —
    the direct regression lock for console-logs-tail-overflow (before the fix the LAST line was the
    one clipped off the bottom, never the first).
    """
    ui, _ = _make_ui(get_url=lambda: "http://192.0.2.50:8099/NEWEST-URL-SENTINEL")
    ui.view = "log"
    for i in range(100):
        ui.log_lines.append(f"OLD-BEYOND-WINDOW-{i:03d} log content")
    ui.dispatch("u")  # the URL is now the newest entry

    out = _render_body_at_size(ui, width=100, height=20)  # 20 rows total → small body region

    assert "NEWEST-URL-SENTINEL" in out, "newest line (URL) was clipped off the bottom (not tailed)"
    assert "OLD-BEYOND-WINDOW-000" not in out, "oldest line should have scrolled out of the tail"


def test_log_body_tails_even_when_last_line_wraps_many_rows():
    """A single very long final line cannot push the newest content off the bottom (physical tail).

    The last entry wraps to far more rows than the body region; the tail must still show its END
    (the newest appended text), proving the guarantee holds for wrapped long lines, not just short
    ones (test_requirements item 3 — robust wrapping handling)."""
    ui, _ = _make_ui()
    ui.view = "log"
    for i in range(40):
        ui.log_lines.append(f"OLD-{i:03d}")
    long_line = "WRAP-START " + ("pad " * 200) + "WRAP-END-SENTINEL"
    ui.log_lines.append(long_line)

    out = _render_body_at_size(ui, width=60, height=18)

    assert "WRAP-END-SENTINEL" in out, "the tail of an over-long final line must remain visible"


def test_log_body_preserves_newest_line_style_after_tail():
    """The tailed body keeps the per-part style spans — the cyan 'u' URL still renders coloured."""
    from rich.console import Console
    from rich.layout import Layout

    ui, _ = _make_ui(get_url=lambda: "http://192.0.2.50:8099/STYLED-URL-SENTINEL")
    ui.view = "log"
    for i in range(80):
        ui.log_lines.append(f"OLD-{i:03d}")
    ui.dispatch("u")  # cyan-styled URL (r8)

    console = Console(width=80, height=18, record=True)
    ui._console = console
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=ConsoleUI.HEADER_SIZE),
        Layout(name="body"),
    )
    layout["body"].update(ui.render_body())
    console.print(layout, height=18)
    ansi = console.export_text(styles=True)

    assert "STYLED-URL-SENTINEL" in ansi
    # cyan survives the tail (ANSI SGR 36 = cyan); the style span travelled with the kept rows
    assert "36m" in ansi or "cyan" in ansi.lower()


def test_log_body_full_join_when_console_is_none():
    """With ui._console is None (pre-Live / unit context) render_body falls back to the full join.

    No crash, and the body still renders the deque entries (the height-unaware fallback). This locks
    the requirement that render_body() is safe before/after Live and in tests that don't wire a
    console — exactly the path the existing markup-safety tests exercise."""
    ui, _ = _make_ui()
    ui.view = "log"
    assert ui._console is None  # default from __init__
    for i in range(5):
        ui.log_lines.append(f"LINE-{i}")
    # render_body must not raise and returns a Panel renderable; rendered text contains every line
    out = _render_body_text(ui, width=80)  # uses its own console, leaves ui._console None
    assert ui._console is None
    for i in range(5):
        assert f"LINE-{i}" in out


def test_console_defaults_to_none_in_init():
    """ConsoleUI.__init__ initializes self._console to None (render_body safe before run())."""
    ui, _ = _make_ui()
    assert ui._console is None
