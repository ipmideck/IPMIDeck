"""AES-256-CBC crypto tests (TEST-03): round-trip + distinct-IV.

encrypt/decrypt are pure functions over a 32-byte key; no DB, no async.
"""

from __future__ import annotations

import os

from backend.core.crypto import decrypt, encrypt


def test_encrypt_decrypt_round_trip():
    key = os.urandom(32)
    assert decrypt(encrypt("hunter2", key), key) == "hunter2"


def test_encrypt_uses_distinct_iv_per_call():
    """A random 16B IV per call -> the same plaintext encrypts to different ciphertext."""
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
