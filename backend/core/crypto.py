"""AES-256-GCM encryption for BMC credentials.

The encryption key itself lives in a file at ``<data_dir>/encryption.key`` (32 raw
bytes), managed by ``AuthManager.initialize()`` — NOT in the SQLite DB. That file MUST
be backed up SEPARATELY from ``data/ipmideck.db``: a stolen DB on its own no longer
decrypts any BMC credentials, and losing the key file makes the stored credentials
unrecoverable. See ``backend/core/auth.py`` for the file-key lifecycle and migration.

Stored values carry a version prefix so the format can change again without a flag day.
Older installs wrote unauthenticated AES-256-CBC with no prefix; those values are still
readable here, and :func:`migrate_credentials` rewrites them in place at startup.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from base64 import b64decode, b64encode
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.padding import PKCS7

logger = logging.getLogger("ipmideck.crypto")

# Marks a value as AES-256-GCM. Base64 never emits ':', so the prefix can never be
# mistaken for payload, and an unprefixed value is unambiguously the older CBC format.
_V2_PREFIX = "v2:"

# 96 bits is the nonce size AES-GCM is specified around; anything else costs an extra
# derivation step inside the cipher for no benefit.
_GCM_NONCE_BYTES = 12

# Bookkeeping identity of the one-shot re-encryption, stored in applied_migrations.
_CRED_MIGRATION_MODULE = "core"
_CRED_MIGRATION_VERSION = "002_authenticated_credentials"


def _set_secure_permissions(path: Path) -> None:
    """Restrict a file to the current owner only.

    POSIX: ``chmod 0o600``. Windows: ``os.chmod`` only flips the read-only bit and
    does NOT touch the NTFS ACL (the file would still inherit the parent dir's ACL,
    often readable by every local user). So on Windows we shell out to ``icacls`` to
    remove inherited ACEs and grant Full control to only the current user. This is the
    documented cross-platform workaround (RESEARCH Pitfall 1). Failure on Windows is
    logged, not raised — the key file is still written, just with weaker permissions.
    """
    path = Path(path)
    if os.name != "nt":
        os.chmod(path, 0o600)
        return
    user = os.environ.get("USERNAME") or "owner"
    try:
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
            check=True, capture_output=True, text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        logging.getLogger("ipmideck.crypto").warning(
            "Failed to set Windows ACL on %s: %s. File may be readable by other local users.",
            path, e,
        )


def encrypt(plaintext: str, key: bytes) -> str:
    """Encrypt a string with AES-256-GCM, return ``v2:base64(nonce + ciphertext + tag)``."""
    nonce = os.urandom(_GCM_NONCE_BYTES)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode(), None)
    return _V2_PREFIX + b64encode(nonce + ct).decode()


def _decrypt_legacy_cbc(token: str, key: bytes) -> str:
    """Decrypt the unauthenticated ``base64(iv + ciphertext)`` written by older versions.

    Kept indefinitely, not as a deprecation courtesy: a backup archive restored from an
    older install is swapped in before the database is opened, so values in this format
    can appear on any boot, at any time in the future.
    """
    raw = b64decode(token)
    iv = raw[:16]
    ct = raw[16:]
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ct) + decryptor.finalize()
    unpadder = PKCS7(128).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()
    return plaintext.decode()


def decrypt(token: str, key: bytes) -> str:
    """Decrypt a stored value, in either the current or the legacy format."""
    if token.startswith(_V2_PREFIX):
        raw = b64decode(token[len(_V2_PREFIX):])
        nonce = raw[:_GCM_NONCE_BYTES]
        ct = raw[_GCM_NONCE_BYTES:]
        return AESGCM(key).decrypt(nonce, ct, None).decode()
    return _decrypt_legacy_cbc(token, key)


def is_legacy_format(token: str | None) -> bool:
    """True if a stored value still uses the unauthenticated format."""
    return bool(token) and not token.startswith(_V2_PREFIX)


async def migrate_credentials(db, key: bytes, data_dir: Path) -> None:
    """Re-encrypt stored BMC credentials in the authenticated format, once.

    Runs at startup, after the encryption key is available and before anything reads a
    credential. Safe to call on every boot: it short-circuits on a bookkeeping row, and
    even without one it only rewrites values that are still in the legacy format.

    Nothing is written until a copy of the database and of the key file exists on disk.
    They are always kept as a pair — the credentials are worthless without the key, so a
    database copy alone would not be a usable rollback point.

    Failure is never fatal. A value that cannot be decrypted is left exactly as it was
    rather than dropped, and if EVERY value fails the key does not belong to this data
    (a mismatched key file, a half-restored backup) — in that case nothing is written at
    all, because rewriting under the wrong key would destroy every credential.
    """
    already_done = await db.fetchone(
        "SELECT 1 FROM applied_migrations WHERE module = ? AND version = ?",
        (_CRED_MIGRATION_MODULE, _CRED_MIGRATION_VERSION),
    )
    if already_done:
        return

    rows = await db.fetchall("SELECT id, username_enc, password_enc FROM servers")
    stale = [
        r for r in rows
        if is_legacy_format(r["username_enc"]) or is_legacy_format(r["password_enc"])
    ]
    if not stale:
        await db.execute(
            "INSERT INTO applied_migrations (module, version) VALUES (?, ?)",
            (_CRED_MIGRATION_MODULE, _CRED_MIGRATION_VERSION),
        )
        await db.commit()
        return

    # Decrypt everything up front. A partial rewrite is harmless (both formats read back
    # fine) but there is no reason to start writing before knowing the key is right.
    rewritten: list[tuple[str, str, str]] = []
    unreadable = 0
    for row in stale:
        try:
            user = decrypt(row["username_enc"], key)
            pwd = decrypt(row["password_enc"], key)
        except Exception:
            unreadable += 1
            continue
        rewritten.append((encrypt(user, key), encrypt(pwd, key), row["id"]))

    if not rewritten:
        logger.error(
            "None of the %d stored credential(s) could be decrypted — leaving them "
            "untouched. The encryption key does not match this database.",
            len(stale),
        )
        return

    backup_path = await _backup_before_rewrite(db, data_dir)
    if backup_path is None:
        logger.error("Could not back up the database — stored credentials left unchanged.")
        return

    try:
        for username_enc, password_enc, server_id in rewritten:
            await db.execute(
                "UPDATE servers SET username_enc = ?, password_enc = ? WHERE id = ?",
                (username_enc, password_enc, server_id),
            )
        if unreadable == 0:
            await db.execute(
                "INSERT INTO applied_migrations (module, version) VALUES (?, ?)",
                (_CRED_MIGRATION_MODULE, _CRED_MIGRATION_VERSION),
            )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Re-encrypting stored credentials failed — nothing was changed.")
        return

    logger.info(
        "Re-encrypted %d stored credential(s) with authenticated encryption; "
        "pre-change copy kept at %s",
        len(rewritten), backup_path,
    )
    if unreadable:
        logger.warning(
            "%d server(s) had credentials that could not be decrypted and were left in "
            "the previous format. Re-enter their BMC credentials to convert them.",
            unreadable,
        )


async def _backup_before_rewrite(db, data_dir: Path) -> Path | None:
    """Copy the database and key file aside. Returns the database copy, or None."""
    db_path = Path(db.db_path)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    db_backup = db_path.with_name(f"{db_path.name}.pre-authenc-{stamp}.bak")
    key_path = data_dir / "encryption.key"
    key_backup = key_path.with_name(f"{key_path.name}.pre-authenc-{stamp}.bak")
    try:
        # Fold the write-ahead log into the main file first, otherwise the copy can be
        # missing the most recent committed rows.
        await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:  # pragma: no cover - checkpointing is best effort
        logger.debug("Could not checkpoint before copying the database", exc_info=True)
    try:
        shutil.copy2(db_path, db_backup)
        if key_path.exists():
            shutil.copy2(key_path, key_backup)
            _set_secure_permissions(key_backup)
    except OSError:
        logger.exception("Failed to write the pre-change copy next to the database.")
        return None
    return db_backup
