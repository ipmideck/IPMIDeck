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
    """dispatch('u') pushes the dashboard URL into the log body (D-15a)."""
    ui, _ = _make_ui(get_url=lambda: "http://h:3000")
    ui.dispatch("u")
    assert ui.log_lines[-1] == "http://h:3000"


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
    assert ui.log_lines[-1] == "http://127.0.0.1:8099"
    assert "0.0.0.0" not in ui.log_lines[-1]


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
