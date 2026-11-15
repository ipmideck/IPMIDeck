"""SEC-01 / F1 — containment unit tests over the pure `_resolve_spa_file()` helper.

These are the deterministic half of the SEC-01 proof: they exercise the decision
function directly, without booting the app. The empirical half — the same
spellings replayed over a raw socket against a live uvicorn — lives in
`tests/integration/test_live_attack_chains.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.main import _resolve_spa_file


@pytest.fixture()
def spa_root(tmp_path: Path) -> Path:
    """A miniature SPA web root plus a sibling file that must stay unreachable."""
    root = tmp_path / "static"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html>spa</html>", encoding="utf-8")
    (root / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (root / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    # The target an attacker is after: a real file OUTSIDE the web root.
    (tmp_path / "secret.toml").write_text("token = 'do-not-leak'", encoding="utf-8")
    return root.resolve()


ESCAPING_PATHS = [
    # The three spellings verified exploitable against the real handler
    # (raw socket, pre-fix): they returned the 4322-byte pyproject.toml.
    "../../secret.toml",
    "../secret.toml",
    # %2e / %2f spellings arrive at the handler already percent-decoded by
    # Starlette, so the decoded form is what the helper must contain.
    "../" * 2 + "secret.toml",
    # Backslash form.
    "..\\..\\secret.toml",
    # Absolute paths.
    "/etc/passwd",
    "/etc/shadow",
    # Windows-shaped.
    "C:/Windows/win.ini",
    # Dot-segment smuggling.
    "....//....//secret.toml",
    # Over-long segment (length cap).
    "a" * 5000,
    # Embedded NUL — Path.resolve() raises ValueError on Linux.
    "index.html\x00.png",
    "\x00",
]


@pytest.mark.parametrize("path", ESCAPING_PATHS)
def test_escaping_paths_never_resolve_outside_root(path: str, spa_root: Path) -> None:
    """Every escaping spelling either falls back (None) or stays under the root."""
    resolved = _resolve_spa_file(path, spa_root)
    if resolved is not None:  # pragma: no cover - defensive: must stay contained
        assert resolved.is_relative_to(spa_root), f"{path!r} escaped to {resolved}"


@pytest.mark.parametrize("path", ESCAPING_PATHS)
def test_escaping_paths_never_return_the_out_of_root_target(path: str, spa_root: Path) -> None:
    """The specific out-of-root file an attacker wants is never handed back."""
    resolved = _resolve_spa_file(path, spa_root)
    assert resolved is None or resolved.name != "secret.toml"


def test_nul_byte_does_not_raise(spa_root: Path) -> None:
    """A NUL byte must be refused, not raised out as an unhandled 500."""
    assert _resolve_spa_file("index.html\x00.png", spa_root) is None


def test_over_long_path_is_refused(spa_root: Path) -> None:
    assert _resolve_spa_file("x" * 1025, spa_root) is None


def test_empty_path_falls_back_to_index(spa_root: Path) -> None:
    """The empty path means "/" — the handler must serve index.html."""
    assert _resolve_spa_file("", spa_root) is None


def test_unknown_spa_route_falls_back_to_index(spa_root: Path) -> None:
    """A React Router client route is not a file: fall back, do not 404."""
    assert _resolve_spa_file("dashboard/servers", spa_root) is None


def test_directory_is_not_served(spa_root: Path) -> None:
    """A directory resolves inside the root but is not a file."""
    assert _resolve_spa_file("assets", spa_root) is None


@pytest.mark.parametrize("path", ["index.html", "favicon.svg", "assets/app.js"])
def test_legitimate_files_still_resolve(path: str, spa_root: Path) -> None:
    resolved = _resolve_spa_file(path, spa_root)
    assert resolved is not None, f"{path!r} should still be served"
    assert resolved.is_file()
    assert resolved.is_relative_to(spa_root)


@pytest.mark.parametrize("path", ["/", "/settings", "/index.html"])
def test_the_page_is_revalidated_after_an_upgrade(client, path: str) -> None:
    """index.html names the hashed bundles of its own build. Served without a cache directive,
    a browser kept the old copy after an upgrade and asked for bundles that were gone."""
    resp = client.get(path)
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-cache"


def test_hashed_bundles_are_not_forced_to_revalidate(client) -> None:
    """The directive is for the page only; the bundles change name when they change."""
    static_assets = Path(__file__).resolve().parents[2] / "backend" / "static" / "assets"
    bundle = next(static_assets.glob("*.js"))
    resp = client.get(f"/assets/{bundle.name}")
    assert resp.status_code == 200
    assert "no-cache" not in resp.headers.get("cache-control", "")
