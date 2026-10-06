"""The two switches in front of the update check, the request floor across restarts, the
unattended check's cadence, what a check reports when it has no fresh answer, and what becomes of
a lookup in flight when the answer is withdrawn.

Neither switch may be argued around: with the configuration switch off nothing reaches the
network even on request, and without the operator's recorded answer the unattended check never
starts. The floor stops a crash-looping process from sending one request per start, while a
normal start still checks.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.core import update_service as svc_mod
from backend.core import updates
from backend.core.branding import VERSION
from backend.core.update_service import (
    CHECK_INTERVAL_SECONDS,
    CONSENT_KEY,
    MIN_AUTO_INTERVAL_SECONDS,
    UpdateService,
)
from backend.core.updates import RELEASES_URL, UpdateProbe


class _FakeDB:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})

    async def get_config(self, key, default=None):
        return self.rows.get(key, default)

    async def set_config(self, key, value):
        self.rows[key] = value


class _YieldingDB(_FakeDB):
    """Hands control back to the event loop on every read, as the real database driver does."""

    async def get_config(self, key, default=None):
        await asyncio.sleep(0)
        return await super().get_config(key, default)


class _ReadOnlyDB(_FakeDB):
    """Answers every read and refuses every write, as a full disk or a read-only volume does."""

    async def set_config(self, key, value):
        raise OSError("attempt to write a readonly database")


class _UnreadableDB(_FakeDB):
    """Fails every read, so the unattended check cannot even ask whether it is wanted."""

    async def get_config(self, key, default=None):
        raise OSError("database is locked")


class _CancelSpy:
    """Stands in for the unattended check's task to see what had happened when it was cancelled."""

    def __init__(self, task, on_cancel):
        self._task = task
        self._on_cancel = on_cancel

    def done(self):
        return self._task.done()

    def cancel(self, *args):
        self._on_cancel()
        return self._task.cancel(*args)

    def __await__(self):
        return self._task.__await__()


def _config(enabled=True):
    return SimpleNamespace(updates=SimpleNamespace(enabled=enabled))


@pytest.fixture
def fetches(monkeypatch):
    calls = []

    def fake(method, **_):
        calls.append(method)
        return UpdateProbe(source=method, latest_version="99.0.0")

    monkeypatch.setattr(svc_mod, "fetch_latest", fake)
    monkeypatch.setattr(svc_mod, "detect_install_method", lambda: "pip")
    return calls


def _serve(monkeypatch, *probes):
    """Answer each lookup with the next of ``probes`` in turn, and record the lookups."""
    pending = list(probes)
    calls = []

    def fake(method, **_):
        calls.append(method)
        return pending.pop(0)

    monkeypatch.setattr(svc_mod, "fetch_latest", fake)
    monkeypatch.setattr(svc_mod, "detect_install_method", lambda: "pip")
    return calls


def _unresolved(version="99.0.0"):
    """A newer version whose release notes could not be read."""
    return UpdateProbe(source="pip", latest_version=version, security_unresolved=True)


async def _until(condition, timeout=3.0):
    """Poll ``condition`` until it holds or ``timeout`` seconds pass; whether it came to hold."""
    for _ in range(int(timeout / 0.01)):
        if condition():
            return True
        await asyncio.sleep(0.01)
    return bool(condition())


def _stored(age_seconds, **extra):
    checked = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return json.dumps({"latest_version": "1.0.0", "checked_at": checked.isoformat(), **extra})


def _pass_time(service, db, seconds):
    """Age both rate limits by ``seconds``: the in-memory attempt time and the stored one."""
    if service._last_attempt is not None:
        service._last_attempt -= seconds
    raw = db.rows.get(svc_mod._RESULT_KEY)
    if raw:
        data = json.loads(raw)
        then = datetime.fromisoformat(data["checked_at"]) - timedelta(seconds=seconds)
        data["checked_at"] = then.isoformat()
        db.rows[svc_mod._RESULT_KEY] = json.dumps(data)


async def _run_loop(service, db, monkeypatch, sleeps, on_sleep=None):
    """Run the unattended loop until its ``sleeps``-th wait and return every wait it asked for.

    Each wait is taken in full, as far as the rate limits can tell, so the next pass sees the
    clock it would really see. ``on_sleep`` runs during each wait but the last; a wait it wakes
    the loop from ends there, and the wait the loop then asks for is recorded like any other.
    """
    delays = []

    async def fake_wait(wake, delay):
        delays.append(delay)
        if len(delays) >= sleeps:
            raise asyncio.CancelledError
        _pass_time(service, db, delay)
        if on_sleep is not None:
            await on_sleep()
        return wake.is_set()

    monkeypatch.setattr(svc_mod, "_sleep_unless_woken", fake_wait)
    with contextlib.suppress(asyncio.CancelledError):
        await service._loop()
    return delays


def _live_loops():
    return [
        task
        for task in asyncio.all_tasks()
        if not task.done()
        and getattr(task.get_coro(), "__qualname__", "") == "UpdateService._loop"
    ]


# --- the two switches ---------------------------------------------------------------------------


async def test_without_a_recorded_answer_the_unattended_check_runs(fetches):
    # On by default: an upgraded instance never runs setup, so it never records an answer, and
    # must still hear about a release. Only an explicit "no" turns the check off.
    service = UpdateService(_FakeDB(), _config(enabled=True))
    assert await service.consent_given() is True
    assert await service.start() is True
    for _ in range(50):
        if fetches:
            break
        await asyncio.sleep(0.01)
    await service.stop()
    assert fetches == ["pip"]


async def test_a_declined_answer_keeps_the_unattended_check_off(fetches):
    service = UpdateService(_FakeDB({CONSENT_KEY: "false"}), _config(enabled=True))
    assert await service.start() is False
    assert fetches == []


async def test_the_configuration_switch_overrides_a_given_answer(fetches):
    service = UpdateService(_FakeDB({CONSENT_KEY: "true"}), _config(enabled=False))
    assert await service.start() is False
    assert service.running() is False
    await asyncio.sleep(0)
    assert fetches == []


async def test_a_request_on_demand_is_refused_when_the_configuration_forbids_it(fetches):
    service = UpdateService(_FakeDB({CONSENT_KEY: "true"}), _config(enabled=False))
    status = await service.check_now()
    assert status.error == "disabled_by_config"
    assert fetches == []


async def test_with_both_switches_on_the_check_runs_at_start(fetches):
    service = UpdateService(_FakeDB({CONSENT_KEY: "true"}), _config(enabled=True))
    assert await service.start() is True
    for _ in range(50):
        if fetches:
            break
        await asyncio.sleep(0.01)
    await service.stop()
    assert fetches == ["pip"]


# --- one unattended check, and only while it is wanted ------------------------------------------


async def test_two_answers_arriving_together_start_a_single_unattended_check(fetches):
    service = UpdateService(_YieldingDB(), _config())
    await asyncio.gather(service.apply_consent(True), service.apply_consent(True))
    started = len(_live_loops())

    await service.apply_consent(False)
    left = _live_loops()
    # Only reached while this test is failing; without it the stray loop leaks into later tests.
    for task in left:
        task.cancel()
    await asyncio.gather(*left, return_exceptions=True)

    assert started == 1
    assert left == [], "a loop outlived the answer being withdrawn"


async def test_a_loop_out_of_reach_of_stop_makes_no_request_once_the_answer_is_withdrawn(
    fetches, monkeypatch
):
    """Run directly, the loop is one the service holds no handle on, so stop() cannot cancel it.
    The withdrawn answer alone has to end it before its next lookup."""
    db = _FakeDB({CONSENT_KEY: "true"})
    service = UpdateService(db, _config())

    async def withdraw():
        await service.apply_consent(False)

    delays = await _run_loop(service, db, monkeypatch, sleeps=3, on_sleep=withdraw)
    assert fetches == ["pip"]
    assert delays == [CHECK_INTERVAL_SECONDS], "the loop went round again after the withdrawal"


async def test_withdrawing_the_answer_mid_lookup_tells_the_worker_thread_before_the_task(
    monkeypatch,
):
    """Cancelling the task cannot stop the thread the lookup runs in, and the cancellation only
    lands on the task's next turn; the thread has to be told directly, and first."""
    received = []

    def slow(method, *, cancel=None, **_):
        received.append(cancel)
        # A lookup between its two requests, which sends the second only if not told to stop.
        if cancel is not None:
            cancel.wait(5)
        return UpdateProbe(source=method, error="cancelled")

    monkeypatch.setattr(svc_mod, "fetch_latest", slow)
    monkeypatch.setattr(svc_mod, "detect_install_method", lambda: "pip")
    service = UpdateService(_FakeDB({CONSENT_KEY: "true"}), _config())
    assert await service.start() is True
    assert await _until(lambda: received)

    told_when_cancelled = []
    service._task = _CancelSpy(
        service._task, lambda: told_when_cancelled.append(received[0].is_set())
    )
    await service.apply_consent(False)

    assert received[0] is not None, "the lookup was given no way to be stopped"
    assert received[0].is_set()
    assert told_when_cancelled == [True], "the worker thread was told only after the task"


async def test_a_lookup_abandoned_by_a_withdrawal_does_not_hold_the_window(monkeypatch):
    """Ticking the box again straight after unticking it checks, rather than repeating a result
    the abandoned lookup never stored."""
    received = []

    def lookup(method, *, cancel=None, **_):
        received.append(cancel)
        if len(received) == 1 and cancel is not None:
            cancel.wait(5)
            return UpdateProbe(source=method, error="cancelled")
        return UpdateProbe(source=method, latest_version="99.0.0")

    monkeypatch.setattr(svc_mod, "fetch_latest", lookup)
    monkeypatch.setattr(svc_mod, "detect_install_method", lambda: "pip")
    db = _FakeDB({CONSENT_KEY: "true"})
    service = UpdateService(db, _config())
    try:
        assert await service.start() is True
        assert await _until(lambda: received)
        await service.apply_consent(False)
        await service.apply_consent(True)
        assert await _until(lambda: len(received) == 2), "re-enabling was served from the cache"
        assert await _until(lambda: svc_mod._RESULT_KEY in db.rows)
    finally:
        await service.stop()
    assert json.loads(db.rows[svc_mod._RESULT_KEY])["latest_version"] == "99.0.0"


# --- the floor across restarts ------------------------------------------------------------------


async def test_a_new_process_does_not_repeat_a_check_made_moments_ago(fetches):
    db = _FakeDB({svc_mod._RESULT_KEY: _stored(age_seconds=60)})
    status = await UpdateService(db, _config()).check_now(MIN_AUTO_INTERVAL_SECONDS)
    assert fetches == []
    assert status.from_cache is True


async def test_a_check_older_than_the_floor_is_repeated(fetches):
    db = _FakeDB({svc_mod._RESULT_KEY: _stored(age_seconds=MIN_AUTO_INTERVAL_SECONDS + 60)})
    await UpdateService(db, _config()).check_now(MIN_AUTO_INTERVAL_SECONDS)
    assert fetches == ["pip"]


async def test_a_timestamp_in_the_future_does_not_suppress_checks(fetches):
    db = _FakeDB({svc_mod._RESULT_KEY: _stored(age_seconds=-3600)})
    await UpdateService(db, _config()).check_now(MIN_AUTO_INTERVAL_SECONDS)
    assert fetches == ["pip"]


async def test_an_unreadable_timestamp_does_not_suppress_checks(fetches):
    db = _FakeDB({svc_mod._RESULT_KEY: json.dumps({"checked_at": "not a date"})})
    await UpdateService(db, _config()).check_now(MIN_AUTO_INTERVAL_SECONDS)
    assert fetches == ["pip"]


async def test_the_loop_waits_out_the_floor_after_a_cached_answer(fetches, monkeypatch):
    db = _FakeDB({CONSENT_KEY: "true", svc_mod._RESULT_KEY: _stored(age_seconds=60)})
    service = UpdateService(db, _config())
    assert await _run_loop(service, db, monkeypatch, sleeps=1) == [MIN_AUTO_INTERVAL_SECONDS]
    assert fetches == []


# --- what a check reports without a fresh answer ------------------------------------------------


async def test_a_failed_lookup_keeps_the_update_an_earlier_one_found(monkeypatch):
    release_url = RELEASES_URL + "/tag/v99.0.0"
    _serve(
        monkeypatch,
        UpdateProbe(
            source="pip", latest_version="99.0.0", is_security=True, release_url=release_url
        ),
        UpdateProbe(source="pip", error="rate_limited"),
    )
    service = UpdateService(_FakeDB(), _config())
    await service.check_now(minimum_interval=0)

    failed = await service.check_now(minimum_interval=0)
    for status in (failed, await service.cached_status()):
        assert status.latest_version == "99.0.0"
        assert status.update_available is True
        assert status.is_security is True
        assert status.release_url == release_url
        assert status.error == "rate_limited"


@pytest.mark.parametrize("kept_version", [VERSION, "0.0.1"])
async def test_a_failed_lookup_does_not_turn_a_kept_version_into_an_update(
    monkeypatch, kept_version
):
    """What a failure keeps is compared with the running version again, not taken as a find."""
    _serve(monkeypatch, UpdateProbe(source="pip", error="unreachable"))
    db = _FakeDB(
        {
            svc_mod._RESULT_KEY: _stored(
                age_seconds=60 * 60, latest_version=kept_version, is_security=True
            )
        }
    )
    service = UpdateService(db, _config())

    failed = await service.check_now(minimum_interval=0)
    for status in (failed, await service.cached_status()):
        assert status.latest_version == kept_version
        assert status.update_available is False
        assert status.error == "unreachable"


async def test_a_lookup_cut_short_stops_its_worker_thread_and_gives_back_its_window(monkeypatch):
    received = []

    def lookup(method, *, cancel=None, **_):
        received.append(cancel)
        if len(received) == 1 and cancel is not None:
            # Held between its requests until told to stop, as behind a slow endpoint.
            cancel.wait(5)
            return UpdateProbe(source=method, error="cancelled")
        return UpdateProbe(source=method, latest_version="99.0.0")

    monkeypatch.setattr(svc_mod, "fetch_latest", lookup)
    monkeypatch.setattr(svc_mod, "detect_install_method", lambda: "pip")
    service = UpdateService(_FakeDB(), _config())

    first = asyncio.create_task(service.check_now())
    assert await _until(lambda: received)
    first.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await first
    assert received[0] is not None and received[0].is_set()

    # Still inside the window the cancelled attempt opened, which it no longer holds.
    status = await service.check_now()
    assert len(received) == 2
    assert status.from_cache is False
    assert status.latest_version == "99.0.0"


async def test_an_answer_the_database_refused_is_not_reported_as_up_to_date(fetches):
    service = UpdateService(_ReadOnlyDB(), _config())
    with contextlib.suppress(OSError):
        await service.check_now()

    # Still inside the window that attempt opened, with nothing stored to repeat.
    status = await service.check_now()
    assert fetches == ["pip"]
    assert status.from_cache is True
    assert status.error == "not_checked"


async def test_a_lookup_that_raises_is_recorded_as_a_failed_attempt(monkeypatch):
    def broken(method, **_):
        raise RuntimeError("a fetcher bug")

    monkeypatch.setattr(svc_mod, "fetch_latest", broken)
    monkeypatch.setattr(svc_mod, "detect_install_method", lambda: "pip")
    db = _FakeDB()
    service = UpdateService(db, _config())

    status = await service.check_now()
    assert status.error == "invalid_response"
    assert json.loads(db.rows[svc_mod._RESULT_KEY])["error"] == "invalid_response"

    again = await service.check_now()
    assert again.from_cache is True
    assert again.error == "invalid_response"


async def test_an_open_security_question_is_stored_reported_and_kept_through_a_failure(
    monkeypatch,
):
    _serve(
        monkeypatch,
        UpdateProbe(source="pip", latest_version="99.0.0", security_unresolved=True),
        UpdateProbe(source="pip", error="unreachable"),
    )
    service = UpdateService(_FakeDB(), _config())

    found = await service.check_now(minimum_interval=0)
    assert found.as_dict()["security_unresolved"] is True
    assert (await service.cached_status()).security_unresolved is True

    await service.check_now(minimum_interval=0)
    kept = await service.cached_status()
    assert kept.update_available is True
    assert kept.security_unresolved is True


# --- the unattended check's cadence -------------------------------------------------------------


async def test_after_failures_the_loop_retries_from_the_floor_doubling_to_the_ceiling(monkeypatch):
    failure = UpdateProbe(source="pip", error="unreachable")
    _serve(
        monkeypatch,
        *[failure] * 7,
        UpdateProbe(source="pip", latest_version=VERSION),
        failure,
    )
    db = _FakeDB({CONSENT_KEY: "true"})
    service = UpdateService(db, _config())

    delays = await _run_loop(service, db, monkeypatch, sleeps=9)
    backing_off = [minutes * 60 for minutes in (15, 30, 60, 120, 240, 360, 360)]
    # A success puts the next failure back at the start of the sequence.
    assert delays == [*backing_off, CHECK_INTERVAL_SECONDS, 15 * 60]


async def test_an_open_security_question_is_asked_again_within_the_hour(monkeypatch):
    _serve(
        monkeypatch,
        UpdateProbe(source="pip", latest_version="99.0.0", security_unresolved=True),
        UpdateProbe(source="pip", latest_version="99.0.0", is_security=True),
    )
    db = _FakeDB({CONSENT_KEY: "true"})
    service = UpdateService(db, _config())

    delays = await _run_loop(service, db, monkeypatch, sleeps=2)
    # Once the notes are read the question is closed and the daily cadence resumes.
    assert delays == [60 * 60, CHECK_INTERVAL_SECONDS]


async def test_an_open_question_gets_six_hourly_re_asks_then_the_daily_cadence(monkeypatch):
    calls = _serve(monkeypatch, *[_unresolved() for _ in range(7)], _unresolved("99.0.1"))
    db = _FakeDB({CONSENT_KEY: "true"})
    service = UpdateService(db, _config())

    delays = await _run_loop(service, db, monkeypatch, sleeps=8)
    assert len(calls) == 8
    assert delays[:7] == [60 * 60] * 6 + [CHECK_INTERVAL_SECONDS]
    # A different version is a different question, with re-asks of its own.
    assert delays[7] == 60 * 60


async def test_reading_the_notes_closes_the_question_and_its_count(monkeypatch):
    _serve(
        monkeypatch,
        *[_unresolved() for _ in range(6)],
        UpdateProbe(source="pip", latest_version="99.0.0"),
        _unresolved(),
    )
    db = _FakeDB({CONSENT_KEY: "true"})
    service = UpdateService(db, _config())

    delays = await _run_loop(service, db, monkeypatch, sleeps=8)
    # Unreadable again later (a rate-limited notes request, say) is a new question.
    assert delays == [60 * 60] * 6 + [CHECK_INTERVAL_SECONDS, 60 * 60]


async def test_failures_after_an_open_question_back_off_rather_than_retry_hourly(monkeypatch):
    failure = UpdateProbe(source="pip", error="unreachable")
    _serve(monkeypatch, _unresolved(), failure, failure, failure)
    db = _FakeDB({CONSENT_KEY: "true"})
    service = UpdateService(db, _config())

    delays = await _run_loop(service, db, monkeypatch, sleeps=4)
    # Each failure keeps the open question, but an endpoint that is down is not asked hourly.
    assert delays == [60 * 60, 15 * 60, 30 * 60, 60 * 60]


async def test_a_check_on_request_that_opens_a_question_shortens_the_loops_daily_wait(
    monkeypatch,
):
    calls = _serve(
        monkeypatch,
        UpdateProbe(source="pip", latest_version=VERSION),
        _unresolved(),
        _unresolved(),
    )
    db = _FakeDB({CONSENT_KEY: "true"})
    service = UpdateService(db, _config())
    pressed = []

    async def press_check_now():
        if not pressed:
            pressed.append(await service.check_now())

    delays = await _run_loop(service, db, monkeypatch, sleeps=3, on_sleep=press_check_now)
    assert pressed[0].security_unresolved is True
    # Up to date at start-up, so a day's wait; Check now cuts it to an hour, and the loop then
    # asks again itself.
    assert delays == [CHECK_INTERVAL_SECONDS, 60 * 60, 60 * 60]
    assert len(calls) == 3


async def test_a_check_on_request_that_opens_a_question_wakes_the_sleeping_loop(monkeypatch):
    """The same in real time, through the real wait: only a wake can end a day within the test."""
    # An hour becomes a twentieth of a second and the floor between unattended lookups is lifted,
    # so the re-ask that follows the wake happens while the test watches.
    monkeypatch.setattr(svc_mod, "_SECURITY_RETRY_SECONDS", 0.05)
    monkeypatch.setattr(svc_mod, "MIN_AUTO_INTERVAL_SECONDS", 0)
    calls = []

    def lookup(method, **_):
        calls.append(method)
        if len(calls) == 1:
            return UpdateProbe(source=method, latest_version=VERSION)
        return _unresolved()

    monkeypatch.setattr(svc_mod, "fetch_latest", lookup)
    monkeypatch.setattr(svc_mod, "detect_install_method", lambda: "pip")
    waits = []
    real_wait = svc_mod._sleep_unless_woken

    async def recorded_wait(wake, delay):
        waits.append(delay)
        return await real_wait(wake, delay)

    monkeypatch.setattr(svc_mod, "_sleep_unless_woken", recorded_wait)
    service = UpdateService(_FakeDB({CONSENT_KEY: "true"}), _config())
    try:
        assert await service.start() is True
        assert await _until(lambda: waits)
        await service.check_now(minimum_interval=0)
        assert await _until(lambda: len(calls) >= 3), "the loop slept on through its day"
    finally:
        await service.stop()
    assert waits[0] == CHECK_INTERVAL_SECONDS
    assert waits[1] <= 0.05


async def test_a_database_that_refuses_the_answer_backs_off_like_any_failure(fetches, monkeypatch):
    db = _ReadOnlyDB({CONSENT_KEY: "true"})
    service = UpdateService(db, _config())

    delays = await _run_loop(service, db, monkeypatch, sleeps=3)
    assert fetches == ["pip"] * 3
    assert delays == [15 * 60, 30 * 60, 60 * 60]


async def test_an_unexpected_error_in_the_loop_backs_off_doubling(fetches, monkeypatch):
    db = _UnreadableDB()
    service = UpdateService(db, _config())

    delays = await _run_loop(service, db, monkeypatch, sleeps=3)
    assert fetches == []
    assert delays == [15 * 60, 30 * 60, 60 * 60]


# --- the cached link ----------------------------------------------------------------------------


async def test_a_foreign_link_in_the_cached_result_is_not_served():
    db = _FakeDB(
        {svc_mod._RESULT_KEY: _stored(age_seconds=60, release_url="javascript:alert(1)")}
    )
    status = await UpdateService(db, _config()).cached_status()
    assert status.release_url == RELEASES_URL


async def test_the_release_notes_survive_the_cache():
    db = _FakeDB({svc_mod._RESULT_KEY: _stored(age_seconds=60, notes="### Added\n\n- A thing.")})
    status = await UpdateService(db, _config()).cached_status()
    assert status.notes == "### Added\n\n- A thing."
    assert status.as_dict()["notes"] == status.notes


async def test_cached_notes_that_are_not_text_are_dropped():
    db = _FakeDB({svc_mod._RESULT_KEY: _stored(age_seconds=60, notes={"html": "<b>x</b>"})})
    assert (await UpdateService(db, _config()).cached_status()).notes is None


# --- the suite's own guard ----------------------------------------------------------------------


def test_a_lookup_nobody_stubbed_fails_instead_of_reaching_the_network(monkeypatch):
    """The suite-wide backstop: a lookup a test forgot to stub ends as "unreachable".

    The real opener is swapped for a recording one first, so that without the backstop this test
    fails on its assertions rather than by making the request it is meant to rule out.
    """
    opened = []

    def recording_open(request, timeout=None):
        opened.append(request.full_url)
        raise ValueError("the opener was reached")

    monkeypatch.setattr(updates, "_OPENER", SimpleNamespace(open=recording_open))
    assert updates.fetch_latest(updates.GIT).error == "unreachable"
    assert opened == []


async def test_the_unattended_check_announces_what_it_found(fetches):
    service = UpdateService(_FakeDB(), _config(enabled=True))
    heard = []
    service.announce = heard.append
    await service.start()
    assert await _until(lambda: heard)
    await service.stop()
    assert heard[0].latest_version == "99.0.0"
    assert heard[0].install_method == "pip"
