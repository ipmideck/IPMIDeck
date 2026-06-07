"""AuthManager tests (TEST-03): session token round-trip / tamper / expiry + lockout.

Uses the conftest `auth_manager` fixture (Strategy C: connected :memory: Database + an
initialized AuthManager). asyncio_mode="auto" => async tests need NO decorator.

CLOCK NOTE (RESEARCH Pitfall 4): session tokens use time.time() (wall clock); the lockout
state uses time.monotonic(). The expiry test monkeypatches `backend.core.auth.time.time`
ONLY — never time.monotonic — so the lockout clock is untouched.
"""

from __future__ import annotations

import backend.core.auth as auth_mod


# === session tokens ===


async def test_session_token_round_trip(auth_manager):
    am, _db = auth_manager
    tok = am.create_session_token("alice")
    assert am.verify_session_token(tok) == "alice"


async def test_session_token_tamper_rejected(auth_manager):
    am, _db = auth_manager
    tok = am.create_session_token("alice")
    # Appending a char breaks the signature -> verification returns None.
    assert am.verify_session_token(tok + "x") is None


async def test_session_token_expiry_rejected(auth_manager, monkeypatch):
    """An expired token verifies to None. Craft expiry by advancing time.time() forward past
    SESSION_EXPIRY_SECONDS AFTER the token is minted. Patch time.time only (Pitfall 4)."""
    am, _db = auth_manager
    real_time = auth_mod.time.time
    tok = am.create_session_token("alice")  # exp = now + SESSION_EXPIRY_SECONDS
    # Jump the wall clock forward past the expiry window.
    future = real_time() + auth_mod.SESSION_EXPIRY_SECONDS + 10
    monkeypatch.setattr(auth_mod.time, "time", lambda: future)
    assert am.verify_session_token(tok) is None


# === brute-force lockout (SEC-03) ===


async def test_lockout_fires_on_sixth_failure(auth_manager):
    am, _db = auth_manager
    for _ in range(6):
        await am.record_failure("bob")
    assert await am.check_lockout("bob") is True


async def test_no_lockout_after_five_failures(auth_manager):
    am, _db = auth_manager
    for _ in range(5):
        await am.record_failure("carol")
    assert await am.check_lockout("carol") is False


async def test_reset_failures_clears_lockout(auth_manager):
    am, _db = auth_manager
    for _ in range(6):
        await am.record_failure("dave")
    assert await am.check_lockout("dave") is True
    await am.reset_failures("dave")
    assert await am.check_lockout("dave") is False


# === user management + auth-enabled gate (coverage-lift over safety-critical auth paths) ===


async def test_create_user_then_verify_password(auth_manager):
    """create_user hashes + stores; verify_password checks against the bcrypt hash."""
    am, _db = auth_manager
    assert await am.has_user() is False
    await am.create_user("alice", "s3cret")
    assert await am.has_user() is True
    assert await am.verify_password("alice", "s3cret") is True
    assert await am.verify_password("alice", "wrong") is False
    # Unknown user returns False (no row).
    assert await am.verify_password("nobody", "whatever") is False


async def test_update_password(auth_manager):
    am, _db = auth_manager
    await am.create_user("alice", "old-pw")
    await am.update_password("alice", "new-pw")
    assert await am.verify_password("alice", "new-pw") is True
    assert await am.verify_password("alice", "old-pw") is False


async def test_replace_user_swaps_single_user(auth_manager):
    """replace_user is a DELETE+INSERT single-user swap; the old username stops verifying."""
    am, _db = auth_manager
    await am.create_user("alice", "pw-a")
    await am.replace_user("bob", "pw-b")
    # Only one user row, and it's bob.
    assert await am.verify_password("bob", "pw-b") is True
    assert await am.verify_password("alice", "pw-a") is False


async def test_replace_user_rejects_blank_credentials(auth_manager):
    import pytest

    am, _db = auth_manager
    with pytest.raises(ValueError):
        await am.replace_user("   ", "pw")
    with pytest.raises(ValueError):
        await am.replace_user("bob", "   ")


async def test_auth_enabled_toggle_round_trips(auth_manager):
    """auth_enabled defaults true; set_auth_enabled(False) flips the DB-backed gate."""
    am, _db = auth_manager
    assert await am.is_auth_enabled() is True  # default "true"
    await am.set_auth_enabled(False)
    assert await am.is_auth_enabled() is False
    await am.set_auth_enabled(True)
    assert await am.is_auth_enabled() is True


async def test_get_encryption_key_is_32_bytes_and_stable(auth_manager):
    """The BMC-credential key is a deterministic 32-byte PBKDF2 derivation of the app secret."""
    am, _db = auth_manager
    key = am.get_encryption_key()
    assert isinstance(key, bytes)
    assert len(key) == 32
    # Deterministic for the same secret.
    assert am.get_encryption_key() == key
