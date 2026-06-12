"""AES-256-CBC encryption for BMC credentials.

The encryption key itself lives in a file at ``<data_dir>/encryption.key`` (32 raw
bytes), managed by ``AuthManager.initialize()`` — NOT in the SQLite DB. That file MUST
be backed up SEPARATELY from ``data/ipmilink.db``: a stolen DB on its own no longer
decrypts any BMC credentials, and losing the key file makes the stored credentials
unrecoverable. See ``backend/core/auth.py`` for the file-key lifecycle and migration.
"""

from __future__ import annotations

import logging
import os
import subprocess
from base64 import b64decode, b64encode
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7


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
        logging.getLogger("ipmilink.crypto").warning(
            "Failed to set Windows ACL on %s: %s. File may be readable by other local users.",
            path, e,
        )


def encrypt(plaintext: str, key: bytes) -> str:
    """Encrypt a string with AES-256-CBC, return base64(iv + ciphertext)."""
    iv = os.urandom(16)
    padder = PKCS7(128).padder()
    padded = padder.update(plaintext.encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ct = encryptor.update(padded) + encryptor.finalize()
    return b64encode(iv + ct).decode()


def decrypt(token: str, key: bytes) -> str:
    """Decrypt a base64(iv + ciphertext) string."""
    raw = b64decode(token)
    iv = raw[:16]
    ct = raw[16:]
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ct) + decryptor.finalize()
    unpadder = PKCS7(128).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()
    return plaintext.decode()
