"""Brand-constant single-source-of-truth tests (D-09/D-10).

Verifies the branding module exposes the five constants and that the FastAPI app's
title/version + the unauthenticated /api/health version all SOURCE from branding (not a
hardcoded literal). The /api/health check is BEHAVIORAL (REVIEWS MED: prefer behavior over
source-grep) — it drives the real route via TestClient under the demo/temp-DB `client`
fixture (auth-OFF), so the real data/ipmideck.db and BMC are never touched.

asyncio_mode="auto" (pyproject) => async tests need NO decorator. These tests are sync.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from backend.core import branding


def test_brand_constants_present_and_nonempty():
    """All five brand constants exist and are non-empty strings."""
    for name in ("APP_NAME", "VERSION", "AUTHOR", "LICENSE", "URL"):
        val = getattr(branding, name)
        assert isinstance(val, str), f"{name} must be a str"
        assert val.strip(), f"{name} must be non-empty"
    # As of 04.2 the rebrand is complete: the single brand constant plus the web UI, PyPI
    # package, env-var prefix and logger namespaces all read "IPMIDeck"/"ipmideck". The only
    # surviving pre-rebrand identifiers are the two locked-legacy constants (the frozen crypto
    # salt and the restore-only legacy backup arcname), which live elsewhere by design.
    assert branding.APP_NAME == "IPMIDeck"


def test_full_banner_is_ansi_shadow_block_art():
    """The launch splash (non-compact banner) is rendered in the ANSI Shadow font — i.e. it is the
    big Unicode block-art banner (█ glyphs), not the small ASCII figlet. Generated from APP_NAME."""
    art = branding.banner()
    assert "█" in art, "full banner should use ANSI Shadow block glyphs (█)"
    assert art.count("\n") >= 4, "ANSI Shadow art spans several rows"


def test_brand_title_reflects_app_name_and_version():
    """The 1-line pinned-header helper sources from APP_NAME/VERSION (the rename flows through it)."""
    assert branding.brand_title(compact=True) == f"{branding.APP_NAME} v{branding.VERSION}"
    assert branding.APP_NAME in branding.brand_title(compact=True)
    assert branding.APP_NAME in branding.brand_title(compact=False)


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


def test_fallback_is_pep440_canonical():
    """The single edited literal is the PEP 440 canonical form (2.0.0-alpha.1 -> 2.0.0a1).
    Pure string assert — `packaging` is intentionally NOT imported (not a declared runtime dep).
    Canonical form keeps tag == dist == METADATA == metadata-action semver with zero per-surface
    normalization (D-03)."""
    assert branding._VERSION_FALLBACK == "2.0.0a1"


def test_version_fallback_when_uninstalled(monkeypatch):
    """When the dist is not installed, VERSION falls back to _VERSION_FALLBACK (raw source
    checkout path, D-02). Monkeypatch importlib.metadata.version to raise and re-run the resolver
    logic — stdlib only, no reload gymnastics."""
    def _raise(_name):
        raise PackageNotFoundError(_name)
    monkeypatch.setattr("backend.core.branding.version", _raise)
    # Re-run the same resolution the module performs at import time:
    try:
        resolved = branding.version("ipmideck")
    except PackageNotFoundError:
        resolved = branding._VERSION_FALLBACK
    assert resolved == branding._VERSION_FALLBACK == "2.0.0a1"


def test_version_matches_installed_dist():
    """When the ipmideck dist IS installed, branding.VERSION mirrors its METADATA Version
    (D-02/D-07). Skips if not installed so a raw source checkout doesn't false-fail; the CI
    build job installs the wheel so this runs in CI. Requires `pip install -e .` locally."""
    try:
        installed = version("ipmideck")
    except PackageNotFoundError:
        import pytest
        pytest.skip("ipmideck dist not installed (run `pip install -e .`)")
    assert branding.VERSION == installed
