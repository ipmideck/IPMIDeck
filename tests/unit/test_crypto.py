"""Credential encryption tests: round-trip, versioning, tamper detection.

encrypt/decrypt are pure functions over a 32-byte key; no DB, no async.
"""

from __future__ import annotations

import os
from base64 import b64encode

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from backend.core.crypto import decrypt, encrypt, is_legacy_format


def _encrypt_legacy(plaintext: str, key: bytes) -> str:
    """Reproduce exactly what older versions wrote: base64(iv + CBC ciphertext)."""
    iv = os.urandom(16)
    padder = PKCS7(128).padder()
    padded = padder.update(plaintext.encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ct = encryptor.update(padded) + encryptor.finalize()
    return b64encode(iv + ct).decode()


def test_encrypt_decrypt_round_trip():
    key = os.urandom(32)
    assert decrypt(encrypt("hunter2", key), key) == "hunter2"


def test_encrypt_uses_distinct_nonce_per_call():
    """A random nonce per call -> the same plaintext encrypts to different ciphertext."""
    key = os.urandom(32)
    assert encrypt("x", key) != encrypt("x", key)
    # Both still decrypt back to the original plaintext.
    key2 = os.urandom(32)
    a = encrypt("payload", key2)
    b = encrypt("payload", key2)
    assert a != b
    assert decrypt(a, key2) == "payload"
    assert decrypt(b, key2) == "payload"


def test_round_trip_multibyte_and_empty():
    key = os.urandom(32)
    assert decrypt(encrypt("", key), key) == ""
    assert decrypt(encrypt("pàsswörd-✓", key), key) == "pàsswörd-✓"


def test_new_values_carry_a_version_marker():
    key = os.urandom(32)
    token = encrypt("hunter2", key)
    assert token.startswith("v2:")
    assert not is_legacy_format(token)


def test_values_written_by_older_versions_still_decrypt():
    """A backup archive from an older install can be restored at any time."""
    key = os.urandom(32)
    legacy = _encrypt_legacy("admin-pass", key)
    assert is_legacy_format(legacy)
    assert decrypt(legacy, key) == "admin-pass"


def test_tampering_with_a_value_is_detected():
    """The whole point of the format change: a modified value must not decrypt."""
    key = os.urandom(32)
    token = encrypt("admin", key)
    body = bytearray(token.encode())
    # Flip a character well inside the base64 payload, past the version marker.
    body[-4] = body[-4] ^ 0x01
    with pytest.raises(Exception):
        decrypt(body.decode(), key)


def test_wrong_key_is_rejected_rather_than_returning_garbage():
    token = encrypt("admin", os.urandom(32))
    with pytest.raises(Exception):
        decrypt(token, os.urandom(32))


def test_is_legacy_format_ignores_empty_values():
    assert is_legacy_format(None) is False
    assert is_legacy_format("") is False
