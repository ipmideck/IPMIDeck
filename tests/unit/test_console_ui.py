"""Headless ConsoleUI dispatch tests (D-01/D-04/D-11/D-13/D-14/D-15a/b/d).

These exercise the CI-assertable surface of the console: the verbosity cycle (default INFO),
the update stub (no network), sub-view switch + ESC/q return, show-URL, the D-15d change-bind
validation + on_change_bind callback, and stop() (event + handler removal). The full interactive
render (rich Live alternate screen) is NOT exercised here — run() gates on isatty() and is
validated in Plan 04's host UAT. We never call run().
"""

from __future__ import annotations

import logging
from collections import deque

from backend.console import ConsoleUI
from backend.core.branding import VERSION


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
