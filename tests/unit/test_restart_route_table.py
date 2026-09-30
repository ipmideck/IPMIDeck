"""Starting the same app object again must not grow its route table or its lifespan chain.

lifespan re-enters on one app object for every TestClient the suite builds (and would for any
in-process restart). Each run used to append another copy of the module routes, /assets and the SPA
catch-all, and every include_router wrapped the router's lifespan_context one level deeper,
until entering it overflowed the stack (after about 95 starts).
"""

from __future__ import annotations

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.routing import Mount

from tests.conftest import _set_temp_env

BOOTS = 5


def _snapshot(app):
    routes = app.router.routes
    return {
        "count": len(routes),
        "lifespan": app.router.lifespan_context,
        "catch_all": sum(
            1 for r in routes if isinstance(r, APIRoute) and r.path == "/{full_path:path}"
        ),
        "assets": sum(1 for r in routes if isinstance(r, Mount) and r.path == "/assets"),
    }


def test_repeated_starts_leave_the_route_table_and_lifespan_unchanged(tmp_path, monkeypatch):
    _set_temp_env(tmp_path, monkeypatch)
    from backend.main import app

    snapshots = []
    for _ in range(BOOTS):
        with TestClient(app) as c:
            assert c.get("/api/health").status_code == 200
            snapshots.append(_snapshot(app))

    first = snapshots[0]
    for later in snapshots[1:]:
        assert later["count"] == first["count"]
        assert later["lifespan"] is first["lifespan"]
    assert first["catch_all"] == 1
    assert first["assets"] <= 1


def test_module_routes_and_the_spa_still_resolve_after_a_restart(client, tmp_path):
    from backend.main import app

    # A second start on the same app object, as an in-process restart does.
    with TestClient(app) as c:
        assert c.get("/api/modules/fanpilot/profiles").status_code != 404
        assert c.get("/api/does-not-exist").status_code == 404
        page = c.get("/some/client/route")
        assert page.status_code == 200
        assert "<html" in page.text.lower()
