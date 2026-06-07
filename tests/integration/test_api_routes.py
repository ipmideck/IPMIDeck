from __future__ import annotations

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
