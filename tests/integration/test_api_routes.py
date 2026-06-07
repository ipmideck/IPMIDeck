"""API integration tests (TEST-04) — FastAPI TestClient against the real ASGI stack.

These tests drive backend.main.app through its real lifespan over an ISOLATED temp SQLite
DB in demo mode (no production data/ipmilink.db, no ipmitool, no real BMC — RESEARCH Pitfall 3).
They use the conftest harness fixtures (03-01):

  * client_auth — auth ENABLED (DB default auth_enabled="true"): the genuine guarded-route
    fixture used for the 401 -> setup -> 200 flow AND the localized login-failure test.
  * client      — auth DISABLED via bm.auth.set_auth_enabled(False) AFTER lifespan (REVIEWS
    HIGH #1: IPMILINK_AUTH_ENABLED is INERT for the runtime gate, which reads the DB). With
    this fixture the guarded /api/servers routes are OPEN (200, not 401).

REVIEWS-driven choices (03-REVIEWS.md):
  * HIGH #1 — CRUD round-trips through `client` (auth off in the DB), proven by test_me_endpoint_open
    asserting auth_enabled is False. The env var alone would leave auth ON and CRUD would 401.
  * HIGH #2 — the localized login-failure test uses `client_auth` + a SEEDED user, because with
    auth OFF /api/auth/login short-circuits to {"success": True, "message": "Auth disabled"}
    (auth_routes.py:87-88) and the localized invalid-credentials path never runs.
  * MED #11 — tests target static /api/* routes (matched before the per-lifespan re-mounted SPA
    catch-all + module routes).
"""

from __future__ import annotations

from backend.core.i18n import t


# --- Task 1: auth-guard contract (SEC-01) + open-route sanity -------------------------------


def test_guarded_route_401_without_cookie(client_auth):
    """Auth ENABLED + no session cookie -> guarded route returns 401 with the SEC-01 shape."""
    resp = client_auth.get("/api/servers")
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "unauthorized"


def test_setup_then_guarded_route_200(client_auth):
    """POST /api/auth/setup sets the session cookie; the SAME client then unlocks the guarded route."""
    setup_resp = client_auth.post(
        "/api/auth/setup", json={"username": "admin", "password": "correcthorse"}
    )
    assert setup_resp.status_code == 200
    assert setup_resp.json()["success"] is True
    # TestClient persists the Set-Cookie `session` on the same client instance.
    assert "session" in client_auth.cookies

    # Re-request the guarded route on the SAME (now-authenticated) client -> 200.
    guarded_resp = client_auth.get("/api/servers")
    assert guarded_resp.status_code == 200
    assert "servers" in guarded_resp.json()


def test_me_endpoint_open(client):
    """The `client` fixture must genuinely disable auth in the DB (guards HIGH #1 regression).

    GET /api/auth/me is UNGUARDED, so it returns 200 in any auth state; what matters is that
    auth_enabled is False, proving bm.auth.set_auth_enabled(False) took effect after lifespan.
    """
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert "auth_enabled" in body
    assert "has_user" in body
    assert "authenticated" in body
    assert body["auth_enabled"] is False


# --- Task 2: server CRUD (auth OFF) + localized login failure (auth ON) ---------------------


def test_server_crud_roundtrip(client):
    """Create -> list (present) -> delete (absent) through the genuinely auth-OFF `client`.

    Works ONLY because the `client` fixture wrote auth_enabled=false to the DB after lifespan
    (HIGH #1); under auth-ON these guarded routes would 401. No request reaches data/ipmilink.db
    (temp DB via the conftest env overrides). create_server's auth.get_encryption_key dependency
    is available because lifespan initialized bm.auth.
    """
    # CREATE
    create_resp = client.post(
        "/api/servers",
        json={
            "name": "Test R720",
            "host": "192.0.2.30",
            "username": "root",
            "password": "calvin",
            "vendor": "dell",
        },
    )
    assert create_resp.status_code == 200, create_resp.text  # not 401 -> auth is truly off
    created = create_resp.json()
    assert created["success"] is True
    server_id = created["server_id"]

    # LIST -> the created server appears
    list_resp = client.get("/api/servers")
    assert list_resp.status_code == 200
    servers = list_resp.json()["servers"]
    match = [s for s in servers if s["id"] == server_id]
    assert len(match) == 1
    assert match[0]["name"] == "Test R720"
    assert match[0]["host"] == "192.0.2.30"

    # DELETE -> success, then no longer listed
    delete_resp = client.delete(f"/api/servers/{server_id}")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["success"] is True

    after_resp = client.get("/api/servers")
    assert after_resp.status_code == 200
    remaining_ids = [s["id"] for s in after_resp.json()["servers"]]
    assert server_id not in remaining_ids


def test_login_failure_localized(client_auth):
    """A failing login honors Accept-Language (02.2 wiring) under auth-ENABLED + a seeded user.

    With auth OFF, /api/auth/login short-circuits to {"success": True, "Auth disabled"}, so the
    localized invalid-credentials path is only reachable under `client_auth` + a real user
    (REVIEWS HIGH #2). Stays under the SEC-03 lockout threshold (6th failure) so the message
    remains "invalid_credentials", not "too_many_attempts".
    """
    # Seed a user (setup succeeds only when no user exists yet; sets a cookie — harmless here).
    setup_resp = client_auth.post(
        "/api/auth/setup", json={"username": "admin", "password": "correcthorse"}
    )
    assert setup_resp.status_code == 200
    assert setup_resp.json()["success"] is True

    # Bad login, Accept-Language: it -> Italian invalid-credentials string.
    it_resp = client_auth.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrong"},
        headers={"Accept-Language": "it"},
    )
    assert it_resp.status_code == 200
    it_body = it_resp.json()
    assert it_body["success"] is False
    assert it_body["error"] == t("invalid_credentials", "it")
    assert it_body["error"] == "Credenziali non valide"

    # Bad login, Accept-Language: en -> English invalid-credentials string (resolver switch).
    en_resp = client_auth.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrong"},
        headers={"Accept-Language": "en"},
    )
    assert en_resp.status_code == 200
    en_body = en_resp.json()
    assert en_body["success"] is False
    assert en_body["error"] == t("invalid_credentials", "en")
    assert en_body["error"] == "Invalid credentials"

    # Resolver actually switched languages between the two requests.
    assert it_body["error"] != en_body["error"]
