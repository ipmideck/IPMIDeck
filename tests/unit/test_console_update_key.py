"""The console update key must perform a real check without blocking the render loop."""

from __future__ import annotations

import asyncio
import io
import logging
import threading

import pytest

from backend.console import ConsoleUI


def _console(**overrides):
    """A ConsoleUI with inert callbacks — enough to drive dispatch() in isolation."""
    kwargs = dict(
        ws_manager=type("W", (), {"connection_count": 0})(),
        get_url=lambda: "http://127.0.0.1:3000",
        get_servers=list,
        on_exit=lambda: None,
        on_restart=lambda: None,
        on_set_verbosity=lambda level: None,
        on_change_bind=lambda host, port: None,
    )
    kwargs.update(overrides)
    return ConsoleUI(**kwargs)


def _lines(console):
    return [str(entry) for entry in console.log_lines]


def test_the_key_schedules_exactly_one_check():
    calls = []
    console = _console(on_check_updates=lambda: calls.append(1))
    console.dispatch("g")
    assert len(calls) == 1


def test_the_key_reports_the_running_version_while_the_check_runs():
    from backend.core.branding import VERSION

    console = _console(on_check_updates=lambda: None)
    console.dispatch("g")
    assert any(VERSION in line for line in _lines(console))


def test_the_key_no_longer_promises_a_future_feature():
    """The old behaviour printed a promise instead of checking. If that string comes back, the
    key has regressed to advertising a capability it does not have."""
    console = _console(on_check_updates=lambda: None)
    console.dispatch("g")
    assert not any("ships with" in line for line in _lines(console))


def test_the_key_never_blocks_the_thread_it_runs_on():
    """dispatch() runs on the key thread; a lookup performed inline would freeze the render loop
    for the duration of the request. The callback must return immediately."""
    finished = threading.Event()

    def slow_but_scheduled():
        # Representative of the real callback: hand the work off and return at once.
        threading.Thread(target=finished.set, daemon=True).start()

    console = _console(on_check_updates=slow_but_scheduled)
    done = threading.Event()

    def press():
        console.dispatch("g")
        done.set()

    threading.Thread(target=press, daemon=True).start()
    assert done.wait(timeout=2), "the update key blocked its caller"
    assert finished.wait(timeout=2)


def test_without_a_check_available_the_key_says_so_rather_than_pretending():
    console = _console(on_check_updates=None)
    console.dispatch("g")
    joined = " ".join(_lines(console))
    assert "switched off" in joined


def test_the_key_result_is_visible_from_a_sub_view():
    """Pressing it while a sub-view is open must switch back to the log, or the answer is drawn
    behind a table the operator cannot see past."""
    console = _console(on_check_updates=lambda: None)
    console.view = "servers"
    console.dispatch("g")
    assert console.view == "log"


def test_the_key_is_recorded_as_an_actionable_press():
    console = _console(on_check_updates=lambda: None)
    console.dispatch("g")
    assert console.last_key == "g"


@pytest.mark.parametrize("key", ["v", "c", "s", "u", "b", "r", "q"])
def test_no_other_key_triggers_a_check(key):
    calls = []
    console = _console(on_check_updates=lambda: calls.append(1))
    console.dispatch(key)
    assert calls == []


def test_the_key_feeds_the_bind_editor_instead_of_checking_while_editing():
    """While the bind editor is open every key is text, so 'g' must type a 'g', not check."""
    calls = []
    console = _console(on_check_updates=lambda: calls.append(1))
    console.input_mode = "bind"
    console.input_buffer = ""
    console.dispatch("g")
    assert calls == []
    assert console.input_buffer == "g"


def test_the_help_bar_still_advertises_the_key():
    """The header renders through rich, so the panel is inspected by rendering it to text."""
    from rich.console import Console

    console_ui = _console(on_check_updates=lambda: None)
    out = Console(width=200, record=True, file=io.StringIO())
    out.print(console_ui.render_header())
    header = out.export_text()
    assert "[g]" in header and "update" in header


# --- what the key reports -----------------------------------------------------------------------


def _report(**fields):
    from backend.core.update_service import UpdateStatus
    from backend.main import _report_update_status

    shown = []
    _report_update_status(UpdateStatus(**fields), lambda line, style="": shown.append(line))
    return shown


def test_a_failed_check_still_reports_the_update_an_earlier_one_found():
    lines = _report(error="rate_limited", update_available=True, latest_version="99.0.0")
    assert any("rate_limited" in line for line in lines)
    assert any("99.0.0" in line for line in lines)


def test_a_failed_check_with_nothing_known_does_not_claim_to_be_up_to_date():
    lines = _report(error="unreachable")
    assert any("unreachable" in line for line in lines)
    assert not any("latest published" in line for line in lines)


def test_a_clean_check_with_nothing_newer_says_so():
    assert any("latest published" in line for line in _report())


def test_a_security_release_is_called_one():
    lines = _report(update_available=True, latest_version="99.0.0", is_security=True)
    assert any("99.0.0" in line and "security release" in line for line in lines)


def test_an_ordinary_release_is_not_called_a_security_release():
    lines = _report(update_available=True, latest_version="99.0.0")
    assert any("99.0.0" in line for line in lines)
    assert not any("security release" in line for line in lines)


def test_the_update_line_points_at_the_release():
    from backend.core.updates import RELEASES_URL

    release_url = RELEASES_URL + "/tag/v99.0.0"
    lines = _report(update_available=True, latest_version="99.0.0", release_url=release_url)
    assert any("99.0.0" in line and release_url in line for line in lines)


# --- the answer reaches the operator whatever the verbosity -------------------------------------


class _Service:
    """Stands in for the update service: answers with ``status`` or raises ``error``."""

    def __init__(self, status=None, error=None):
        self.status = status
        self.error = error

    async def check_now(self):
        if self.error is not None:
            raise self.error
        return self.status


def _check_at(level, service):
    """Run the console's check with the body wired the way run() wires it, at ``level``.

    run() attaches a DequeLogHandler to the root logger and the verbosity key sets the root level,
    so a log record below that level never reaches the body. Rebuilding that here is what lets
    these tests tell an answer shown directly from one that was only logged.
    """
    from backend.console import DequeLogHandler
    from backend.main import _run_console_update_check

    console = _console(on_check_updates=lambda: None, verbosity=level)
    root = logging.getLogger()
    handler = DequeLogHandler(console.log_lines)
    previous = root.level
    root.addHandler(handler)
    root.setLevel(level)
    try:
        asyncio.run(_run_console_update_check(service, console.report))
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)
    return console


@pytest.mark.parametrize("level", ["WARNING", "ERROR"])
def test_the_up_to_date_answer_is_shown_at_a_quiet_verbosity(level):
    """WARNING is the quietest step of the verbosity key and ERROR is what logging.level: error
    gives. The "Checking…" line is shown at both, so the answer to it must be as well."""
    from backend.core.update_service import UpdateStatus

    console = _check_at(level, _Service(status=UpdateStatus()))
    assert any("latest published" in line for line in _lines(console))


def test_a_found_update_is_shown_at_a_quiet_verbosity():
    from backend.core.update_service import UpdateStatus

    status = UpdateStatus(update_available=True, latest_version="99.0.0")
    console = _check_at("ERROR", _Service(status=status))
    assert any("99.0.0" in line for line in _lines(console))


def test_a_check_that_raises_is_still_answered():
    console = _check_at("ERROR", _Service(error=RuntimeError("boom")))
    assert any("could not be completed" in line for line in _lines(console))


def test_an_answer_arriving_while_a_table_is_open_leaves_it_open():
    """The answer comes some time after the key; the operator may have opened a table since."""
    console = _console(on_check_updates=lambda: None)
    console.view = "servers"
    console.report("an answer")
    assert console.view == "servers"
    assert "an answer" in _lines(console)


# --- whether the key is wired at all --------------------------------------------------------------


def _wired(early_cfg):
    from backend.main import _console_update_callback

    def callback():
        return None

    return _console_update_callback(early_cfg, callback) is callback


def test_the_key_is_wired_when_the_switch_is_on():
    from backend.core.config import AppConfig, UpdatesConfig

    assert _wired(AppConfig(updates=UpdatesConfig(enabled=True)))


def test_the_key_is_not_wired_when_the_switch_is_off():
    from backend.core.config import AppConfig, UpdatesConfig

    assert not _wired(AppConfig(updates=UpdatesConfig(enabled=False)))


def test_the_key_stays_wired_when_the_configuration_could_not_be_read():
    """The service reads the switch again before every lookup and refuses when it is off, so
    keeping the key wired here cannot open a socket the configuration forbids."""
    assert _wired(None)
