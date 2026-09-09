"""Startup conversion of stored BMC credentials to the authenticated format.

Exercises the real Database + AuthManager on a tmp-dir SQLite file, because the
conversion copies the database and the key file aside before writing.
"""

from __future__ import annotations

import os
from base64 import b64encode
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from backend.core.crypto import (
    decrypt,
    encrypt,
    is_legacy_format,
    migrate_credentials,
)


def _encrypt_legacy(plaintext: str, key: bytes) -> str:
    iv = os.urandom(16)
    padder = PKCS7(128).padder()
    padded = padder.update(plaintext.encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ct = encryptor.update(padded) + encryptor.finalize()
    return b64encode(iv + ct).decode()


async def _add_server(db, server_id: str, username_enc: str, password_enc: str) -> None:
    await db.execute(
        "INSERT INTO servers (id, name, host, username_enc, password_enc) "
        "VALUES (?, ?, ?, ?, ?)",
        (server_id, f"srv-{server_id}", "192.0.2.10", username_enc, password_enc),
    )
    await db.commit()


def _backups(data_dir: Path) -> list[Path]:
    return sorted(data_dir.glob("*.pre-authenc-*.bak"))


@pytest.mark.asyncio
async def test_legacy_credentials_are_converted_and_still_readable(auth_manager, tmp_path):
    am, db = auth_manager
    key = am.get_encryption_key()
    creds = {
        "a": ("root", "calvin"),
        "b": ("ADMIN", "pàssw0rd-✓"),
        "c": ("operator", ""),
    }
    for sid, (user, pwd) in creds.items():
        await _add_server(db, sid, _encrypt_legacy(user, key), _encrypt_legacy(pwd, key))

    await migrate_credentials(db, key, tmp_path)

    rows = await db.fetchall("SELECT id, username_enc, password_enc FROM servers")
    assert len(rows) == 3
    for row in rows:
        assert not is_legacy_format(row["username_enc"])
        assert not is_legacy_format(row["password_enc"])
        expected_user, expected_pwd = creds[row["id"]]
        assert decrypt(row["username_enc"], key) == expected_user
        assert decrypt(row["password_enc"], key) == expected_pwd


@pytest.mark.asyncio
async def test_the_database_and_key_are_copied_aside_before_any_write(auth_manager, tmp_path):
    am, db = auth_manager
    key = am.get_encryption_key()
    await _add_server(db, "a", _encrypt_legacy("root", key), _encrypt_legacy("calvin", key))

    assert _backups(tmp_path) == []
    await migrate_credentials(db, key, tmp_path)

    names = [p.name for p in _backups(tmp_path)]
    assert any(n.startswith("ipmideck.db.pre-authenc-") for n in names), names
    assert any(n.startswith("encryption.key.pre-authenc-") for n in names), names

    # The key copy must be the same bytes, or the rollback point is useless.
    key_backup = next(p for p in _backups(tmp_path) if p.name.startswith("encryption.key"))
    assert key_backup.read_bytes() == (tmp_path / "encryption.key").read_bytes()


@pytest.mark.asyncio
async def test_running_twice_changes_nothing_the_second_time(auth_manager, tmp_path):
    am, db = auth_manager
    key = am.get_encryption_key()
    await _add_server(db, "a", _encrypt_legacy("root", key), _encrypt_legacy("calvin", key))

    await migrate_credentials(db, key, tmp_path)
    first = await db.fetchone("SELECT username_enc FROM servers WHERE id = 'a'")
    backups_after_first = len(_backups(tmp_path))

    await migrate_credentials(db, key, tmp_path)
    second = await db.fetchone("SELECT username_enc FROM servers WHERE id = 'a'")

    assert second["username_enc"] == first["username_enc"]
    assert len(_backups(tmp_path)) == backups_after_first


@pytest.mark.asyncio
async def test_a_greenfield_database_takes_no_backup(auth_manager, tmp_path):
    am, db = auth_manager
    await migrate_credentials(db, am.get_encryption_key(), tmp_path)
    assert _backups(tmp_path) == []


@pytest.mark.asyncio
async def test_an_unreadable_row_is_left_alone_and_the_others_convert(auth_manager, tmp_path):
    """One corrupt value must never cost the operator the rest of their servers."""
    am, db = auth_manager
    key = am.get_encryption_key()
    await _add_server(db, "good", _encrypt_legacy("root", key), _encrypt_legacy("calvin", key))
    await _add_server(db, "junk", "not-real-ciphertext", "not-real-ciphertext")

    await migrate_credentials(db, key, tmp_path)

    good = await db.fetchone("SELECT username_enc FROM servers WHERE id = 'good'")
    junk = await db.fetchone("SELECT username_enc FROM servers WHERE id = 'junk'")
    assert decrypt(good["username_enc"], key) == "root"
    assert junk["username_enc"] == "not-real-ciphertext"


@pytest.mark.asyncio
async def test_a_key_that_does_not_match_the_data_writes_nothing(auth_manager, tmp_path):
    """A mismatched key must not be used to rewrite every credential into noise."""
    am, db = auth_manager
    real_key = am.get_encryption_key()
    await _add_server(
        db, "a", _encrypt_legacy("root", real_key), _encrypt_legacy("calvin", real_key)
    )
    before = await db.fetchone("SELECT username_enc, password_enc FROM servers WHERE id = 'a'")

    await migrate_credentials(db, os.urandom(32), tmp_path)

    after = await db.fetchone("SELECT username_enc, password_enc FROM servers WHERE id = 'a'")
    assert after["username_enc"] == before["username_enc"]
    assert after["password_enc"] == before["password_enc"]
    assert _backups(tmp_path) == []
    # And the conversion must not be recorded, so a correct key can still do the job later.
    assert await db.fetchone(
        "SELECT 1 FROM applied_migrations WHERE module = 'core'"
    ) is None


@pytest.mark.asyncio
async def test_a_mixed_table_is_fully_readable(auth_manager, tmp_path):
    """A crash mid-conversion leaves both formats in place; both must still read."""
    am, db = auth_manager
    key = am.get_encryption_key()
    await _add_server(db, "old", _encrypt_legacy("root", key), _encrypt_legacy("calvin", key))
    await _add_server(db, "new", encrypt("ADMIN", key), encrypt("secret", key))

    rows = await db.fetchall("SELECT id, username_enc FROM servers")
    assert {r["id"]: decrypt(r["username_enc"], key) for r in rows} == {
        "old": "root",
        "new": "ADMIN",
    }

    await migrate_credentials(db, key, tmp_path)
    rows = await db.fetchall("SELECT id, username_enc FROM servers")
    assert {r["id"]: decrypt(r["username_enc"], key) for r in rows} == {
        "old": "root",
        "new": "ADMIN",
    }


def test_the_copies_are_never_shipped_inside_a_backup_archive():
    """Backups are credential-grade already; the pre-change copies must not double that."""
    from backend.api.system_routes import ALLOWED_BACKUP_FILES

    assert not any(name.endswith(".bak") for name in ALLOWED_BACKUP_FILES)
