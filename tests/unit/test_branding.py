"""Brand-constant single-source-of-truth tests (D-09/D-10).

Verifies the branding module exposes the five constants and that the FastAPI app's
title/version + the unauthenticated /api/health version all SOURCE from branding (not a
hardcoded literal). The /api/health check is BEHAVIORAL (REVIEWS MED: prefer behavior over
source-grep) — it drives the real route via TestClient under the demo/temp-DB `client`
fixture (auth-OFF), so the real data/ipmilink.db and BMC are never touched.

asyncio_mode="auto" (pyproject) => async tests need NO decorator. These tests are sync.
"""

from __future__ import annotations

from pathlib import Path

from backend.core import branding


def test_brand_constants_present_and_nonempty():
    """All five brand constants exist and are non-empty strings."""
    for name in ("APP_NAME", "VERSION", "AUTHOR", "LICENSE", "URL"):
        val = getattr(branding, name)
        assert isinstance(val, str), f"{name} must be a str"
        assert val.strip(), f"{name} must be non-empty"
    # Name stays "IPMILink" this phase (04.2 flips APP_NAME).
    assert branding.APP_NAME == "IPMILink"


def test_app_title_and_version_source_from_branding():
    """FastAPI app.title/app.version mirror the brand constants (no hardcoded literal)."""
    import backend.main as m

    assert m.app.title == branding.APP_NAME
    assert m.app.version == branding.VERSION


def test_health_version_matches_branding(client):
    """BEHAVIORAL: GET /api/health (unauthenticated) returns branding.VERSION.

    Uses the auth-OFF demo/temp-DB `client` fixture so no real hardware/DB is touched.
    """
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["version"] == branding.VERSION


def test_health_version_literal_absent_from_source():
    """Belt-and-suspenders regression lock: the hardcoded version literal no longer lives in
    system_routes.py (the behavioral test above is the PRIMARY check)."""
    src = Path("backend/api/system_routes.py").read_text(encoding="utf-8")
    assert '"2.0.0-alpha.1"' not in src
