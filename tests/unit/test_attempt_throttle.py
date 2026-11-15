"""Per-source throttling of credential-verifying requests, and the timing equaliser."""

from __future__ import annotations

import time

import pytest

from backend.core.auth import ATTEMPT_LIMIT, ATTEMPT_WINDOW_SECONDS, _MAX_TRACKED_SOURCES


@pytest.mark.asyncio
async def test_a_source_gets_exactly_the_allowance(auth_manager):
    am, _ = auth_manager
    for i in range(ATTEMPT_LIMIT):
        assert await am.consume_attempt_slot("192.0.2.5") is True, f"attempt {i + 1}"
    assert await am.consume_attempt_slot("192.0.2.5") is False


@pytest.mark.asyncio
async def test_sources_are_counted_separately(auth_manager):
    am, _ = auth_manager
    for _ in range(ATTEMPT_LIMIT):
        await am.consume_attempt_slot("192.0.2.5")
    assert await am.consume_attempt_slot("192.0.2.5") is False
    assert await am.consume_attempt_slot("198.51.100.9") is True


@pytest.mark.asyncio
async def test_the_window_reopens(auth_manager, monkeypatch):
    am, _ = auth_manager
    for _ in range(ATTEMPT_LIMIT):
        await am.consume_attempt_slot("192.0.2.5")
    assert await am.consume_attempt_slot("192.0.2.5") is False

    real = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: real() + ATTEMPT_WINDOW_SECONDS + 1)
    assert await am.consume_attempt_slot("192.0.2.5") is True


@pytest.mark.asyncio
async def test_a_successful_attempt_still_consumes_a_slot(auth_manager):
    """Otherwise a caller who already knows the password has no limit at all."""
    am, db = auth_manager
    await am.create_user("operator", "correct-horse")
    for _ in range(ATTEMPT_LIMIT):
        assert await am.consume_attempt_slot("192.0.2.5") is True
        assert await am.verify_password("operator", "correct-horse") is True
    assert await am.consume_attempt_slot("192.0.2.5") is False


@pytest.mark.asyncio
async def test_throttling_never_locks_the_account_out(auth_manager):
    """A limiter that fed the account counter would be a denial-of-service lever."""
    am, _ = auth_manager
    for _ in range(ATTEMPT_LIMIT * 4):
        await am.consume_attempt_slot("192.0.2.5")
    assert await am.check_lockout("operator") is False
    assert am._fail_state == {}


@pytest.mark.asyncio
async def test_the_source_table_stays_bounded(auth_manager):
    """A caller cycling addresses must not be able to grow the table without limit."""
    am, _ = auth_manager
    for i in range(_MAX_TRACKED_SOURCES + 500):
        await am.consume_attempt_slot(f"198.51.100.{i}")
    assert len(am._attempt_window) <= _MAX_TRACKED_SOURCES


@pytest.mark.asyncio
async def test_the_failure_table_stays_bounded(auth_manager):
    am, _ = auth_manager
    for i in range(_MAX_TRACKED_SOURCES + 500):
        await am.record_failure(f"user-{i}")
    assert len(am._fail_state) <= _MAX_TRACKED_SOURCES


@pytest.mark.asyncio
async def test_an_enormous_username_does_not_become_an_enormous_key(auth_manager):
    am, _ = auth_manager
    await am.record_failure("a" * 100_000)
    assert all(len(k) <= 128 for k in am._fail_state)


@pytest.mark.asyncio
async def test_an_unknown_username_costs_the_same_as_a_wrong_password(auth_manager):
    """The gap between the two used to name the single valid account outright."""
    am, _ = auth_manager
    await am.create_user("operator", "correct-horse")

    async def _time(username: str) -> float:
        start = time.perf_counter()
        await am.verify_password(username, "wrong-password")
        return time.perf_counter() - start

    known = sorted([await _time("operator") for _ in range(5)])[2]
    unknown = sorted([await _time("nobody-here") for _ in range(5)])[2]

    # Before the fix the unknown path skipped bcrypt entirely and was orders of
    # magnitude faster. Anything within 3x is indistinguishable across a network.
    assert unknown > known / 3, f"known={known:.4f}s unknown={unknown:.4f}s"
    assert unknown < known * 3, f"known={known:.4f}s unknown={unknown:.4f}s"
