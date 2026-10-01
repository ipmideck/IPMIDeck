"""The two switches in front of the update check, the request floor across restarts, the
unattended check's cadence, and what a check reports when it has no fresh answer.

Neither switch may be argued around: with the configuration switch off nothing reaches the
network even on request, and without the operator's recorded answer the unattended check never
starts. The floor stops a crash-looping process from sending one request per start, while a
normal start still checks.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
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


def _config(enabled=True):
    return SimpleNamespace(updates=SimpleNamespace(enabled=enabled))


@pytest.fixture
def fetches(monkeypatch):
    calls = []

    def fake(method):
        calls.append(method)
        return UpdateProbe(source=method, latest_version="99.0.0")

    monkeypatch.setattr(svc_mod, "fetch_latest", fake)
    monkeypatch.setattr(svc_mod, "detect_install_method", lambda: "pip")
    return calls


def _serve(monkeypatch, *probes):
    """Answer each lookup with the next of ``probes`` in turn, and record the lookups."""
    pending = list(probes)
    calls = []

    def fake(method):
        calls.append(method)
        return pending.pop(0)

    monkeypatch.setattr(svc_mod, "fetch_latest", fake)
    monkeypatch.setattr(svc_mod, "detect_install_method", lambda: "pip")
    return calls


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
    clock it would really see. ``on_sleep`` runs during each wait but the last.
    """
    delays = []

    async def fake_sleep(delay):
        delays.append(delay)
        if len(delays) >= sleeps:
            raise asyncio.CancelledError
        _pass_time(service, db, delay)
        if on_sleep is not None:
            await on_sleep()

    monkeypatch.setattr(svc_mod.asyncio, "sleep", fake_sleep)
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


async def test_without_a_recorded_answer_the_unattended_check_never_starts(fetches):
    service = UpdateService(_FakeDB(), _config(enabled=True))
    assert await service.start() is False
    assert service.running() is False
    await asyncio.sleep(0)
    assert fetches == []


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
    slept = []

    async def fake_sleep(delay):
        slept.append(delay)
        raise asyncio.CancelledError

    monkeypatch.setattr(svc_mod.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await service._loop()
    assert slept == [MIN_AUTO_INTERVAL_SECONDS]
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


async def test_a_lookup_cut_short_is_not_reported_as_up_to_date(monkeypatch):
    release = threading.Event()
    calls = []

    def blocked(method):
        calls.append(method)
        release.wait(5)
        return UpdateProbe(source=method, latest_version="99.0.0")

    monkeypatch.setattr(svc_mod, "fetch_latest", blocked)
    monkeypatch.setattr(svc_mod, "detect_install_method", lambda: "pip")
    service = UpdateService(_FakeDB(), _config())

    first = asyncio.create_task(service.check_now())
    for _ in range(200):
        if calls:
            break
        await asyncio.sleep(0.01)
    first.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await first
    release.set()

    # Still inside the window the cancelled attempt opened, with nothing stored to repeat.
    status = await service.check_now()
    assert calls == ["pip"]
    assert status.from_cache is True
    assert status.error == "not_checked"


async def test_a_lookup_that_raises_is_recorded_as_a_failed_attempt(monkeypatch):
    def broken(method):
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


# --- the cached link ----------------------------------------------------------------------------


async def test_a_foreign_link_in_the_cached_result_is_not_served():
    db = _FakeDB(
        {svc_mod._RESULT_KEY: _stored(age_seconds=60, release_url="javascript:alert(1)")}
    )
    status = await UpdateService(db, _config()).cached_status()
    assert status.release_url == RELEASES_URL


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
