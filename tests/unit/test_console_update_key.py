"""The console update key must perform a real check without blocking the render loop."""

from __future__ import annotations

import io
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


def _report(caplog, **fields):
    from backend.core.update_service import UpdateStatus
    from backend.main import _report_update_status

    caplog.clear()
    with caplog.at_level("INFO", logger="ipmideck"):
        _report_update_status(UpdateStatus(**fields))
    return [r.getMessage() for r in caplog.records]


def test_a_failed_check_still_reports_the_update_an_earlier_one_found(caplog):
    lines = _report(
        caplog, error="rate_limited", update_available=True, latest_version="99.0.0"
    )
    assert any("rate_limited" in line for line in lines)
    assert any("99.0.0" in line for line in lines)


def test_a_failed_check_with_nothing_known_does_not_claim_to_be_up_to_date(caplog):
    lines = _report(caplog, error="unreachable")
    assert any("unreachable" in line for line in lines)
    assert not any("latest published" in line for line in lines)


def test_a_clean_check_with_nothing_newer_says_so(caplog):
    assert any("latest published" in line for line in _report(caplog))
