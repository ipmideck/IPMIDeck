"""The two switches in front of the update check, and the request floor across restarts.

Neither switch may be argued around: with the configuration switch off nothing reaches the
network even on request, and without the operator's recorded answer the unattended check never
starts. The floor stops a crash-looping process from sending one request per start, while a
normal start still checks.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.core import update_service as svc_mod
from backend.core.update_service import (
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


def _stored(age_seconds, **extra):
    checked = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return json.dumps({"latest_version": "1.0.0", "checked_at": checked.isoformat(), **extra})


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
    db = _FakeDB({svc_mod._RESULT_KEY: _stored(age_seconds=60)})
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


# --- the cached link ----------------------------------------------------------------------------


async def test_a_foreign_link_in_the_cached_result_is_not_served():
    db = _FakeDB(
        {svc_mod._RESULT_KEY: _stored(age_seconds=60, release_url="javascript:alert(1)")}
    )
    status = await UpdateService(db, _config()).cached_status()
    assert status.release_url == RELEASES_URL
