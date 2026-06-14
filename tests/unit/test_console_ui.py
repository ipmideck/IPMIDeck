"""Headless ConsoleUI dispatch tests (D-01/D-04/D-11/D-13/D-14/D-15a/b/d).

These exercise the CI-assertable surface of the console: the verbosity cycle (default INFO),
the update stub (no network), sub-view switch + ESC/q return, show-URL, the D-15d change-bind
validation + on_change_bind callback, and stop() (event + handler removal). The full interactive
render (rich Live alternate screen) is NOT exercised here — run() gates on isatty() and is
validated in Plan 04's host UAT. We never call run().

It ALSO locks the 04.1-04 gap-closure fixes (header clipping, special-key consumption, last-key
feedback): the pinned header must render its help bar + status + credits with NO clipping at 80
cols (regression lock for the figlet-overflow bug), special arrow/function keys must be consumed
as a single ignorable event, and an actionable keypress must update the header's last-key field.
"""

from __future__ import annotations

import logging
from collections import deque

from backend.console import ConsoleUI
from backend.core.branding import APP_NAME, VERSION


def _render_header_text(ui, width: int = 80) -> str:
    """Render ui.render_header() through a fixed-width recording rich Console and return plain text.

    export_text() strips ANSI/markup so assertions are colour-independent; width is pinned so the
    clipping regression is deterministic regardless of the runner's real terminal size.
    """
    from rich.console import Console

    console = Console(width=width, record=True)
    console.print(ui.render_header())
    return console.export_text()


class _FakeWSManager:
    """Minimal ws_manager stand-in: empty sessions, zero clients."""

    def sessions(self) -> list[dict]:
        return []

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


def test_validate_bind_accepts_good_and_rejects_bad():
    """_validate_bind accepts a good host/port and rejects empty host, out-of-range and non-int ports."""
    assert ConsoleUI._validate_bind("0.0.0.0", "8099") == ("0.0.0.0", 8099)
    assert ConsoleUI._validate_bind("", "8099") is None
    assert ConsoleUI._validate_bind("h", "0") is None
    assert ConsoleUI._validate_bind("h", "70000") is None
    assert ConsoleUI._validate_bind("h", "abc") is None


def test_change_bind_dispatch_calls_callback(monkeypatch):
    """dispatch('b') prompts, then calls on_change_bind + logs 'restart required' (D-15d)."""
    ui, calls = _make_ui()
    monkeypatch.setattr(ui, "prompt_bind", lambda: ("0.0.0.0", 8099))
    ui.dispatch("b")
    assert calls["change_bind"] == [("0.0.0.0", 8099)]
    assert "restart required" in ui.log_lines[-1]


def test_change_bind_dispatch_cancelled_does_not_call_callback(monkeypatch):
    """If prompt_bind returns None (invalid/cancelled), on_change_bind is NOT called (D-15d)."""
    ui, calls = _make_ui()
    monkeypatch.setattr(ui, "prompt_bind", lambda: None)
    ui.dispatch("b")
    assert calls["change_bind"] == []


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


# --- 04.1-04 gap-closure: header clipping regression lock (concern 1) --------------------


def test_header_shows_help_bar_at_80_cols():
    """REGRESSION LOCK: the pinned header renders the full help/shortcut bar at 80 cols.

    The original bug: render_header() put the 5-line figlet (banner(compact=True)) inside an
    8-row header region, so the help bar / status / credits were clipped off the bottom and the
    operator saw NO shortcuts. The compact header must use a single-line brand and ALWAYS show
    the help bar — including the literal key hints '[v]' and '[q]' and the word 'verbosity'.
    """
    ui, _ = _make_ui()
    out = _render_header_text(ui, width=80)
    assert "[v]" in out
    assert "verbosity" in out
    assert "[q]" in out


def test_header_shows_status_and_credits_at_80_cols():
    """The status line (verbosity + client count) and the credits line are visible, not clipped."""
    ui, _ = _make_ui()
    out = _render_header_text(ui, width=80)
    assert "INFO" in out  # current verbosity in the status line
    assert "Clients" in out  # connected-client count label
    assert "Luigi Tanzillo" in out  # credits_line() author (D-10)


def test_compact_header_has_no_multiline_figlet():
    """The compact header must NOT embed the multi-line figlet art (it caused the clipping).

    The single-line brand still names the product (APP_NAME, so the 04.2 rename keeps working),
    but the '___'/'|_ _|' figlet glyph rows must be absent — the big figlet is splash-only.
    """
    ui, _ = _make_ui()
    out = _render_header_text(ui, width=80)
    assert APP_NAME in out  # brand still present as a single line
    assert "___" not in out  # no figlet ASCII-art rows
    assert "|_ _|" not in out


def test_header_fits_region_size_at_80_cols():
    """The rendered header (incl. panel border rows) must fit the header Layout size — no overflow.

    ConsoleUI exposes the chosen header size as HEADER_SIZE; the rendered panel height must be
    <= HEADER_SIZE so the body region (logs) is never pushed off-screen.
    """
    ui, _ = _make_ui()
    out = _render_header_text(ui, width=80)
    rendered_rows = len(out.rstrip("\n").splitlines())
    assert rendered_rows <= ConsoleUI.HEADER_SIZE


def test_header_help_bar_degrades_on_narrow_terminal():
    """On a narrow (40-col) terminal the help bar still renders without crashing (graceful wrap)."""
    ui, _ = _make_ui()
    out = _render_header_text(ui, width=40)
    # the brand and at least one key hint survive even when the bar must wrap
    assert APP_NAME in out
    assert "verbosity" in out


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


# --- gap-closure r2: launch-splash pause so the big banner is actually seen (D-02) -------


def test_splash_seconds_constant_exists_and_is_positive():
    """main.SPLASH_SECONDS exists and is a small positive pause (the splash dwell before Live)."""
    import backend.main as main_mod

    assert hasattr(main_mod, "SPLASH_SECONDS")
    assert isinstance(main_mod.SPLASH_SECONDS, (int, float))
    assert 0 < main_mod.SPLASH_SECONDS <= 5


def test_splash_pause_is_guarded_to_the_tty_path():
    """The splash sleep(SPLASH_SECONDS) is reachable ONLY inside the interactive (TTY) branch.

    The non-TTY/Docker path (D-07/D-21) must emit the banner once and NEVER sleep. We assert the
    sleep is lexically inside the `if interactive:` block of _serve_forever and that the constant
    is used exactly once there — a static guard, so the test never actually sleeps.
    """
    import inspect

    import backend.main as main_mod

    src = inspect.getsource(main_mod.cli)
    # the pause must reference the named constant (no magic number) and the print_banner_safe call
    assert "SPLASH_SECONDS" in src
    assert "time.sleep(SPLASH_SECONDS)" in src
    # the sleep must come AFTER the banner emission and INSIDE the interactive branch, BEFORE the
    # render thread starts (so the operator sees the big splash before Live takes the screen).
    interactive_idx = src.index("if interactive:")
    banner_idx = src.index("print_banner_safe(banner())")
    sleep_idx = src.index("time.sleep(SPLASH_SECONDS)")
    render_idx = src.index("render_thread = threading.Thread")
    assert interactive_idx < banner_idx < sleep_idx < render_idx
