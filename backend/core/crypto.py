"""AES-256-CBC encryption for BMC credentials."""

from __future__ import annotations

import os
from base64 import b64decode, b64encode

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7


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
