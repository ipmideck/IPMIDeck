"""API route-surface contract snapshot (C2, route-SURFACE coverage).

This test pins the post-lifespan HTTP route surface to the EXACT set that existed
immediately BEFORE the Phase-6 UI redesign and remains live at the Phase-6 tip
(b207817): 58 HTTP (path, method) entries + 1 /ws WebSocket route. If any route is
added, removed, renamed, or has its declared methods changed, the snapshot diff FAILS
and names the exact offending routes.

WHY the `client` fixture (post-lifespan), NOT an import-time enumeration:
  The 19 module routes (/api/modules/...) are mounted ONLY inside the app lifespan
  (backend/core/modules.py mount_routes, prefix f"/api/modules/{mod.id}"). Enumerating
  app.routes at import time would MISS all of them. The `client` conftest fixture has
  already entered the TestClient lifespan, so the full surface is present.

C2 PROOF FRAMING (read before trusting this as a contract proof):
  This test pins the route SURFACE only — path + method + /ws existence. It does NOT
  prove response body / status code / error-body shape. Body/status/error-shape
  invariance across Phase-6 is proven by the COMBINATION of:
    (a) the EMPTY backend-product diff a9d2f12..b207817 (asserted in
        test_baseline_invariance.py) — the handler bodies are byte-identical, AND
    (b) the response-shape assertions in test_api_routes.py (success/servers/mode/error
        keys) — the live body shapes are exercised.
  The route snapshot is route-SURFACE coverage, NOT body-shape coverage.

UPDATE POLICY:
  This snapshot is a DRIFT DETECTOR, not a freeze. When a FUTURE phase legitimately adds,
  removes, or renames a route, update the EXPECTED set IN THE SAME COMMIT as the route
  change (so the change is intentional and reviewed, never silent drift).
"""

from __future__ import annotations

# The pinned route SURFACE contract (verified live, post-lifespan, at Phase-6 tip b207817).
# 58 HTTP (path, method) entries + the ("/ws", "") WebSocketRoute entry = 59 tuples.
# Methods are the explicitly-declared verbs (auto-added HEAD/OPTIONS excluded). Some paths
# repeat with different methods (e.g. /api/servers GET+POST) — that is correct.
EXPECTED = {
    ("/api/admin/modules", "GET"),
    ("/api/admin/modules/{module_id}", "PUT"),
    ("/api/auth/configure", "POST"),
    ("/api/auth/login", "POST"),
    ("/api/auth/logout", "POST"),
    ("/api/auth/me", "GET"),
    ("/api/auth/setup", "POST"),
    ("/api/auth/status", "GET"),
    ("/api/auth/toggle", "POST"),
    ("/api/config", "GET"),
    ("/api/dashboard/context", "GET"),
    ("/api/dashboard/context", "PUT"),
    ("/api/dashboard/layout", "DELETE"),
    ("/api/dashboard/layout", "GET"),
    ("/api/dashboard/layout", "PUT"),
    ("/api/dashboard/widgets", "GET"),
    ("/api/health", "GET"),
    ("/api/logs", "GET"),
    ("/api/modules/fanpilot/profiles", "GET"),
    ("/api/modules/fanpilot/profiles", "POST"),
    ("/api/modules/fanpilot/profiles/{profile_id}", "DELETE"),
    ("/api/modules/fanpilot/profiles/{profile_id}", "GET"),
    ("/api/modules/fanpilot/profiles/{profile_id}", "PUT"),
    ("/api/modules/fanpilot/{server_id}/mode", "POST"),
    ("/api/modules/fanpilot/{server_id}/status", "GET"),
    ("/api/modules/fru/{server_id}", "GET"),
    ("/api/modules/fru/{server_id}/refresh", "POST"),
    ("/api/modules/power/{server_id}/command", "POST"),
    ("/api/modules/power/{server_id}/status", "GET"),
    ("/api/modules/sel/{server_id}", "GET"),
    ("/api/modules/sel/{server_id}/clear", "POST"),
    ("/api/modules/sel/{server_id}/export", "GET"),
    ("/api/modules/sel/{server_id}/info", "GET"),
    ("/api/modules/sel/{server_id}/refresh", "POST"),
    ("/api/modules/sensors/{server_id}/history", "GET"),
    ("/api/modules/sensors/{server_id}/latest", "GET"),
    ("/api/modules/sensors/{server_id}/types", "GET"),
    ("/api/search", "GET"),
    ("/api/servers", "GET"),
    ("/api/servers", "POST"),
    ("/api/servers/test", "POST"),
    ("/api/servers/{server_id}", "DELETE"),
    ("/api/servers/{server_id}", "GET"),
    ("/api/servers/{server_id}", "PUT"),
    ("/api/servers/{server_id}/test", "POST"),
    ("/api/system/app-config/{key}", "GET"),
    ("/api/system/app-config/{key}", "PUT"),
    ("/api/system/backup", "POST"),
    ("/api/system/db-stats", "GET"),
    ("/api/system/energy-reset", "POST"),
    ("/api/system/energy-resets", "GET"),
    ("/api/system/gen-cert", "POST"),
    ("/api/system/history-csv", "GET"),
    ("/api/system/https", "PUT"),
    ("/api/system/restore", "POST"),
    ("/api/system/retention-cleanup-now", "POST"),
    ("/api/system/retention-days", "GET"),
    ("/api/system/retention-days", "PUT"),
    ("/ws", ""),  # WebSocketRoute: no .methods
}

# Auto-added verbs FastAPI attaches to GET routes — excluded from the declared contract.
_IMPLICIT_METHODS = {"HEAD", "OPTIONS"}


def _live_surface(app) -> set[tuple[str, str]]:
    """Enumerate the live (post-lifespan) /api + /ws route surface as (path, method) pairs.

    For HTTP routes, iterate the declared methods and drop the auto-added HEAD/OPTIONS.
    The /ws WebSocketRoute has no `.methods` attribute, so it is emitted as ("/ws", "").
    """
    live: set[tuple[str, str]] = set()
    for r in app.routes:
        path = getattr(r, "path", "")
        if not (path.startswith("/api") or path == "/ws"):
            continue
        methods = getattr(r, "methods", None)
        if methods is None:  # WebSocketRoute — no methods
            live.add((path, ""))
            continue
        for method in methods:
            if method in _IMPLICIT_METHODS:
                continue
            live.add((path, method))
    return live


def test_route_surface_is_invariant(client):
    """The live post-lifespan route surface must equal the pinned pre-Phase-6 contract.

    Uses the `client` fixture so module routes (mounted only inside lifespan) ARE present.
    A drift names the exact added/removed routes so the offender is obvious.
    """
    live = _live_surface(client.app)
    assert live == EXPECTED, (
        "API route surface drifted from the pre-Phase-6 contract.\n"
        f"Added: {sorted(live - EXPECTED)}\n"
        f"Removed: {sorted(EXPECTED - live)}"
    )


def test_route_surface_counts(client):
    """Exactly 58 HTTP (path, method) entries + exactly 1 /ws entry.

    A count regression is named even before the full set diff, so an added/removed route
    is caught at the coarsest granularity first.
    """
    live = _live_surface(client.app)
    ws_entries = {entry for entry in live if entry == ("/ws", "")}
    http_entries = live - ws_entries
    assert len(http_entries) == 58, (
        f"expected 58 HTTP (path, method) entries, found {len(http_entries)}"
    )
    assert len(ws_entries) == 1, f"expected exactly 1 /ws entry, found {len(ws_entries)}"
