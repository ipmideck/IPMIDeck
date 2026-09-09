"""Session-expiry configurability tests (SX0-A).

Proves the three legs of `IPMIDECK_AUTH_SESSION_EXPIRY` / `auth.session_expiry`:
  1. parse_duration_seconds is a pure, never-raising string/int -> seconds parser with a 24h
     fallback for anything invalid (unit tests, no I/O).
  2. AuthManager mints a token whose exp - iat == its session_expiry_seconds (unit, no config).
  3. End-to-end: a non-default env value drives the issued cookie Max-Age through the real app
     lifespan (config re-load + wiring), using the conftest env-before-import pattern.

asyncio_mode="auto" (pyproject) => async tests need NO decorator.
"""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from backend.core.config import parse_duration_seconds


# === 1. pure parser ===


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("24h", 86400),
        ("90m", 5400),
        ("1h", 3600),
        ("1d", 86400),
        ("45s", 45),
        ("3600", 3600),  # bare integer string = seconds
        (3600, 3600),  # bare integer
        ("  1H  ", 3600),  # whitespace + case-insensitive
        ("2D", 172800),
    ],
)
def test_parse_duration_valid(value, expected):
    assert parse_duration_seconds(value, default=86400) == expected


@pytest.mark.parametrize(
    "value",
    ["", "abc", "-5", "0", "12x", None, "1.5h", "h", "  ", "0s", "0h", True, False],
)
def test_parse_duration_invalid_returns_default(value):
    """Invalid / non-positive input falls back to the default and never raises."""
    assert parse_duration_seconds(value, default=86400) == 86400


def test_parse_duration_respects_custom_default():
    assert parse_duration_seconds("nonsense", default=1234) == 1234


def test_parse_duration_clamps_absurd_values():
    """A typo cannot grant a session a lifetime measured in years."""
    from backend.core.config import MAX_DURATION_SECONDS

    assert parse_duration_seconds("9999d") == MAX_DURATION_SECONDS
    assert parse_duration_seconds(10**12) == MAX_DURATION_SECONDS
    # A legitimate value below the cap is untouched.
    assert parse_duration_seconds("7d") == 604800


def test_parse_duration_logs_the_fallback(caplog):
    """The operator can discover that the configured value was never in effect."""
    with caplog.at_level("WARNING", logger="ipmideck.config"):
        assert parse_duration_seconds("not-a-duration", default=86400) == 86400
    assert any("not-a-duration" in r.getMessage() for r in caplog.records)


# === 2. token exp reflects the instance session_expiry_seconds ===


def _decode_payload(token: str) -> dict:
    """Decode the base64url-encoded JSON payload half of a session token."""
    b64 = token.rsplit(".", 1)[0]
    raw = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)).decode()
    return json.loads(raw)


async def test_token_exp_matches_session_expiry_seconds(auth_manager):
    am, _db = auth_manager
    am.session_expiry_seconds = 3600
    payload = _decode_payload(am.create_session_token("alice"))
    assert payload["exp"] - payload["iat"] == 3600


async def test_token_exp_default_is_24h(auth_manager):
    """A fresh AuthManager (no config wiring) keeps the 24h fallback default."""
    am, _db = auth_manager
    payload = _decode_payload(am.create_session_token("alice"))
    assert payload["exp"] - payload["iat"] == 86400


# === 3. end-to-end: env value -> cookie Max-Age ===


def test_configured_expiry_drives_cookie_max_age(tmp_path, monkeypatch):
    """IPMIDECK_AUTH_SESSION_EXPIRY="1h" (auth ON, fresh temp DB) yields Max-Age=3600 on the
    session cookie AND a token whose exp - iat == 3600.

    Env is set BEFORE importing backend.main (conftest Pitfall 3): the lifespan re-runs
    load_config() so the override + SX0-A wiring apply. Throwaway synthetic creds only.
    """
    monkeypatch.setenv("IPMIDECK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IPMIDECK_DEMO", "true")
    monkeypatch.setenv("IPMIDECK_DATA_DB_PATH", str(tmp_path / "ipmideck.db"))
    monkeypatch.setenv("IPMIDECK_AUTH_SESSION_EXPIRY", "1h")

    from backend.main import app  # import AFTER env is set

    with TestClient(app) as c:
        # Auth defaults ON in the fresh temp DB, so /setup issues the first session cookie.
        r = c.post("/api/auth/setup", json={"username": "admin", "password": "correcthorse"})
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True
        set_cookie = r.headers["set-cookie"]
        assert "Max-Age=3600" in set_cookie, set_cookie
        # The token payload exp window matches too (not just the cookie attribute).
        token = c.cookies["session"]
        payload = _decode_payload(token)
        assert payload["exp"] - payload["iat"] == 3600
