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
    """The BMC-credential key (04-W4-04 file-based) is a stable 32-byte value in memory."""
    am, _db = auth_manager
    key = am.get_encryption_key()
    assert isinstance(key, bytes)
    assert len(key) == 32
    # Stable within the process (returns the same loaded file key each call).
    assert am.get_encryption_key() == key


# === 04-W4-04: crash-safe at-rest crypto migration (Decisions H, I) ===


async def test_initialize_greenfield_creates_file_key(tmp_path):
    """First run with no app_secret and no key file → a 32-byte encryption.key is written
    and NO app_secret row is created (session secret lives separately)."""
    from backend.core.auth import AuthManager
    from backend.core.database import Database

    db = Database(str(tmp_path / "ipmideck.db"))
    await db.connect()
    am = AuthManager(db)
    await am.initialize()
    key_file = tmp_path / "encryption.key"
    assert key_file.exists() and len(key_file.read_bytes()) == 32
    assert await db.get_config("app_secret") is None
    assert await db.get_config("session_secret") is not None
    assert am.get_encryption_key() == key_file.read_bytes()
    await db.close()


async def test_initialize_migrates_app_secret_to_file_key(tmp_path):
    """A legacy DB (app_secret + creds encrypted with the PBKDF2 key) migrates: app_secret is
    deleted, the file key is written, creds re-encrypt and still decrypt, and the session secret
    preserves the old app_secret value so existing cookies stay valid."""
    import hashlib

    from backend.core.auth import AuthManager
    from backend.core.crypto import decrypt, encrypt
    from backend.core.database import Database

    secret = "f00dface" * 8
    old_key = hashlib.pbkdf2_hmac("sha256", secret.encode(), b"ipmilink-cred-enc", 100000, dklen=32)

    db = Database(str(tmp_path / "ipmideck.db"))
    await db.connect()
    await db.set_config("app_secret", secret)
    await db.execute(
        "INSERT INTO servers (id, name, host, username_enc, password_enc) VALUES (?,?,?,?,?)",
        ("s1", "lab", "10.0.0.1", encrypt("admin", old_key), encrypt("pw", old_key)),
    )
    await db.commit()

    am = AuthManager(db)
    await am.initialize()

    assert (tmp_path / "encryption.key").exists()
    assert await db.get_config("app_secret") is None
    assert await db.get_config("session_secret") == secret  # cookie continuity
    fk = am.get_encryption_key()
    assert fk != old_key
    row = await db.fetchone("SELECT username_enc, password_enc FROM servers WHERE id='s1'")
    assert decrypt(row["username_enc"], fk) == "admin"
    assert decrypt(row["password_enc"], fk) == "pw"
    await db.close()


async def test_initialize_dual_exist_wrong_key_keeps_app_secret(tmp_path):
    """Both encryption.key and app_secret present but the file key does NOT decrypt existing
    creds → app_secret is KEPT, the runtime key falls back to the PBKDF2 derivation, no data loss."""
    import hashlib

    from backend.core.auth import AuthManager
    from backend.core.crypto import decrypt, encrypt
    from backend.core.database import Database

    secret = "abad1dea" * 8
    old_key = hashlib.pbkdf2_hmac("sha256", secret.encode(), b"ipmilink-cred-enc", 100000, dklen=32)

    db = Database(str(tmp_path / "ipmideck.db"))
    await db.connect()
    await db.set_config("app_secret", secret)
    await db.execute(
        "INSERT INTO servers (id, name, host, username_enc, password_enc) VALUES (?,?,?,?,?)",
        ("s1", "lab", "10.0.0.1", encrypt("admin", old_key), encrypt("pw", old_key)),
    )
    await db.commit()
    # Plant a bogus 32-byte file key that cannot decrypt the OLD-key rows.
    (tmp_path / "encryption.key").write_bytes(b"\x02" * 32)

    am = AuthManager(db)
    await am.initialize()

    assert await db.get_config("app_secret") == secret  # NOT deleted
    fk = am.get_encryption_key()
    assert fk == old_key  # fell back to the PBKDF2 key
    row = await db.fetchone("SELECT username_enc FROM servers WHERE id='s1'")
    assert decrypt(row["username_enc"], fk) == "admin"
    await db.close()


async def test_initialize_dual_exist_correct_key_finishes_migration(tmp_path):
    """Both files present and the file key DOES decrypt (a partial migration that committed the
    re-encrypt but crashed before deleting app_secret) → app_secret is removed, file key adopted."""
    from backend.core.auth import AuthManager
    from backend.core.crypto import decrypt, encrypt
    from backend.core.database import Database

    new_key = b"\x07" * 32  # the durable file key
    db = Database(str(tmp_path / "ipmideck.db"))
    await db.connect()
    # Rows already re-encrypted with new_key; app_secret lingering from the crash.
    await db.set_config("app_secret", "dead" * 16)
    await db.execute(
        "INSERT INTO servers (id, name, host, username_enc, password_enc) VALUES (?,?,?,?,?)",
        ("s1", "lab", "10.0.0.1", encrypt("admin", new_key), encrypt("pw", new_key)),
    )
    await db.commit()
    (tmp_path / "encryption.key").write_bytes(new_key)

    am = AuthManager(db)
    await am.initialize()

    assert await db.get_config("app_secret") is None  # finished
    fk = am.get_encryption_key()
    assert fk == new_key
    row = await db.fetchone("SELECT username_enc FROM servers WHERE id='s1'")
    assert decrypt(row["username_enc"], fk) == "admin"
    await db.close()


async def test_get_encryption_key_before_init_raises(tmp_path):
    """Calling get_encryption_key() before initialize() raises (no silent empty key)."""
    import pytest

    from backend.core.auth import AuthManager
    from backend.core.database import Database

    db = Database(str(tmp_path / "ipmideck.db"))
    await db.connect()
    am = AuthManager(db)
    with pytest.raises(RuntimeError):
        am.get_encryption_key()
    await db.close()
