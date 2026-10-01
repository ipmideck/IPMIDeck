"""The update surface: the offline routes, and the ones that must not exist when suppressed."""

from __future__ import annotations

import asyncio
import json
import os

import pytest
from fastapi.testclient import TestClient

from backend.core import update_service as svc_mod
from backend.core.updates import UpdateProbe


def _run(coro):
    """Drive a coroutine from a sync fixture, matching the shared client fixture's approach."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("event loop closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# Booting the application is deliberately NOT done once per test.
#
# backend.main keeps its database, config and services in module-level globals, so two live
# instances cannot coexist: the second boot's globals are the ones every route handler sees.
#
# So there is exactly ONE live instance at a time, rebooted only when a test needs the other
# configuration. Tests are grouped by configuration below, so a reboot happens only where one
# group gives way to the next. Per-test isolation is restored before each test by clearing the
# stored rows, stopping the unattended check and resetting the in-memory rate-limit state.
class _Instance:
    """The single live application instance, rebooted only when the configuration must change."""

    def __init__(self) -> None:
        self.client: TestClient | None = None
        self.enabled: bool | None = None
        self._ctx = None
        self._dir = None

    def get(self, tmp_path_factory, enabled: bool):
        if self.enabled == enabled and self.client is not None:
            return self.client
        self.close()
        self._dir = tmp_path_factory.mktemp("updates-on" if enabled else "updates-off")
        os.environ["IPMIDECK_DATA_DIR"] = str(self._dir)
        os.environ["IPMIDECK_DEMO"] = "true"
        os.environ["IPMIDECK_DATA_DB_PATH"] = str(self._dir / "ipmideck.db")
        os.environ["IPMIDECK_UPDATES_ENABLED"] = "true" if enabled else "false"
        import backend.main as bm

        self._ctx = TestClient(bm.app)
        self.client = self._ctx.__enter__()
        _run(bm.auth.set_auth_enabled(False))
        self.enabled = enabled
        return self.client

    def close(self) -> None:
        if self._ctx is not None:
            self._ctx.__exit__(None, None, None)
        self._ctx = None
        self.client = None
        self.enabled = None


@pytest.fixture(scope="module")
def _instance():
    inst = _Instance()
    yield inst
    inst.close()
    for key in (
        "IPMIDECK_DATA_DIR",
        "IPMIDECK_DEMO",
        "IPMIDECK_DATA_DB_PATH",
        "IPMIDECK_UPDATES_ENABLED",
    ):
        os.environ.pop(key, None)


@pytest.fixture
def open_client(_instance, tmp_path_factory):
    """The live instance with the configuration switch on."""
    import backend.main as bm

    client = _instance.get(tmp_path_factory, True)
    _reset_update_state(bm)
    return client, bm


@pytest.fixture
def suppressed_client(_instance, tmp_path_factory):
    """The live instance with the configuration switch off."""
    import backend.main as bm

    client = _instance.get(tmp_path_factory, False)
    _reset_update_state(bm)
    return client, bm


def _reset_update_state(bm) -> None:
    """Back to "nothing recorded, nothing cached, no rate limit held".

    Without this a stored answer or a cached result from one test would decide another's
    outcome, and the rate limit from a check would silently turn the next check into a cache read.
    """
    _run(bm.db.set_config("updates.check_enabled", "false"))
    _run(bm.db.set_config("updates.last_result", ""))
    _run(bm.update_service.stop())
    bm.update_service._last_attempt = None
    bm.update_service._backoff = svc_mod._BACKOFF_START_SECONDS


# --- the offline routes -------------------------------------------------------------------------


def test_the_version_history_is_served_without_touching_the_network(open_client, monkeypatch):
    client, bm = open_client

    def forbidden(*args, **kwargs):
        raise AssertionError("the version history must not perform a lookup")

    monkeypatch.setattr("backend.core.updates._urlopen", forbidden)
    body = client.get("/api/updates/changelog").json()
    assert body["success"] is True
    versions = [e["version"] for e in body["entries"]]
    assert "2.0.1" in versions and "2.0.0" in versions
    assert body["current_version"]


def test_the_history_marks_a_security_release_apart(open_client):
    client, _ = open_client
    entries = client.get("/api/updates/changelog").json()["entries"]
    assert any(e["is_security"] for e in entries), "no entry carries the security marker"
    assert any(not e["is_security"] for e in entries), "every entry claims to be a security release"


def test_the_state_route_reports_both_switches(open_client):
    client, _ = open_client
    body = client.get("/api/updates/state").json()
    assert body["enabled"] is True
    assert body["consent"] is False  # nothing was answered yet
    assert body["update_available"] is False
    assert body["install_method"]


def test_the_state_route_performs_no_lookup(open_client, monkeypatch):
    client, _ = open_client

    def forbidden(*args, **kwargs):
        raise AssertionError("reading the cached state must not perform a lookup")

    monkeypatch.setattr("backend.core.updates._urlopen", forbidden)
    assert client.get("/api/updates/state").json()["success"] is True


# --- suppression --------------------------------------------------------------------------------


def test_the_check_route_does_not_exist_when_suppressed(suppressed_client):
    """Not a 403 from a guard — the route is simply not registered, so no code path is left
    that could open a socket.

    The status is 405 rather than 404 because the single-page-app catch-all declares only GET,
    so an unmatched POST is refused by the router before anything of ours runs. What matters is
    that no handler exists: the assertion on the registered paths is the load-bearing one.
    """
    client, bm = suppressed_client
    registered = {r.path for r in bm.app.routes if hasattr(r, "path")}
    assert "/api/updates/check" not in registered
    assert "/api/updates/consent" not in registered
    assert client.post("/api/updates/check").status_code in (404, 405)
    assert client.put("/api/updates/consent", json={"enabled": True}).status_code in (404, 405)


def test_the_history_still_reads_when_suppressed(suppressed_client):
    """Suppressing the lookup must not take the version history with it."""
    client, _ = suppressed_client
    assert client.get("/api/updates/changelog").json()["success"] is True


def test_the_unattended_check_is_not_running_when_suppressed(suppressed_client):
    client, bm = suppressed_client
    # Consent given, so only the configuration switch can be what keeps it off.
    _run(bm.db.set_config("updates.check_enabled", "true"))
    assert _run(bm.update_service.start()) is False
    assert bm.update_service.running() is False


# --- checking -----------------------------------------------------------------------------------


def test_a_check_reports_the_resolved_versions(open_client, monkeypatch):
    client, bm = open_client
    monkeypatch.setattr(
        "backend.core.update_service.fetch_latest",
        lambda method: UpdateProbe(source=method, latest_version="99.0.0", release_url="u"),
    )
    body = client.post("/api/updates/check").json()
    assert body["success"] is True
    assert body["latest_version"] == "99.0.0"
    assert body["update_available"] is True
    assert body["checked_at"]


def test_a_second_check_inside_the_window_is_served_from_cache(open_client, monkeypatch):
    client, bm = open_client
    calls = []

    def counted(method):
        calls.append(method)
        return UpdateProbe(source=method, latest_version="99.0.0")

    monkeypatch.setattr("backend.core.update_service.fetch_latest", counted)
    client.post("/api/updates/check")
    second = client.post("/api/updates/check").json()
    assert len(calls) == 1, "the rate limit did not hold"
    assert second["from_cache"] is True
    assert second["latest_version"] == "99.0.0"


def test_a_failed_check_reports_a_reason_rather_than_an_error_page(open_client, monkeypatch):
    client, _ = open_client
    monkeypatch.setattr(
        "backend.core.update_service.fetch_latest",
        lambda method: UpdateProbe(source=method, error="unreachable"),
    )
    body = client.post("/api/updates/check").json()
    assert body["success"] is False
    assert body["error"] == "unreachable"


def test_a_security_release_is_carried_through_the_check(open_client, monkeypatch):
    client, _ = open_client
    monkeypatch.setattr(
        "backend.core.update_service.fetch_latest",
        lambda method: UpdateProbe(source=method, latest_version="99.0.0", is_security=True),
    )
    assert client.post("/api/updates/check").json()["is_security"] is True


def test_an_unknown_security_answer_is_carried_through_the_check(open_client, monkeypatch):
    client, _ = open_client
    monkeypatch.setattr(
        "backend.core.update_service.fetch_latest",
        lambda method: UpdateProbe(
            source=method, latest_version="99.0.0", security_unresolved=True
        ),
    )
    assert client.post("/api/updates/check").json()["security_unresolved"] is True
    assert client.get("/api/updates/state").json()["security_unresolved"] is True


# --- consent ------------------------------------------------------------------------------------


def test_consent_is_persisted_and_takes_effect_immediately(open_client, monkeypatch):
    client, bm = open_client
    monkeypatch.setattr(
        "backend.core.update_service.fetch_latest",
        lambda method: UpdateProbe(source=method, latest_version="1.0.0"),
    )
    body = client.put("/api/updates/consent", json={"enabled": True}).json()
    assert body["success"] is True and body["running"] is True
    assert client.get("/api/updates/state").json()["consent"] is True

    off = client.put("/api/updates/consent", json={"enabled": False}).json()
    assert off["running"] is False
    assert client.get("/api/updates/state").json()["consent"] is False
    assert bm.update_service.running() is False


def test_the_cached_result_survives_a_read_and_reports_the_stored_version(open_client, monkeypatch):
    client, bm = open_client
    monkeypatch.setattr(
        "backend.core.update_service.fetch_latest",
        lambda method: UpdateProbe(source=method, latest_version="99.0.0", release_url="u"),
    )
    client.post("/api/updates/check")
    stored = _run(bm.db.get_config("updates.last_result"))
    assert json.loads(stored)["latest_version"] == "99.0.0"
    state = client.get("/api/updates/state").json()
    assert state["latest_version"] == "99.0.0"
    assert state["from_cache"] is True


def test_an_unreadable_cached_result_degrades_instead_of_breaking_the_page(open_client):
    client, bm = open_client
    _run(bm.db.set_config("updates.last_result", "{not json"))
    body = client.get("/api/updates/state").json()
    assert body["success"] is True
    assert body["latest_version"] is None


def test_the_consent_key_is_readable_through_the_generic_config_route(open_client, monkeypatch):
    client, _ = open_client
    # Consenting starts the unattended check, whose first act is a lookup.
    monkeypatch.setattr(
        "backend.core.update_service.fetch_latest",
        lambda method: UpdateProbe(source=method, latest_version="1.0.0"),
    )
    client.put("/api/updates/consent", json={"enabled": True})
    body = client.get("/api/system/app-config/updates.check_enabled").json()
    assert body["success"] is True and body["value"] is True


def test_the_consent_key_is_not_writable_through_the_generic_config_route(
    open_client, monkeypatch
):
    """A write there would store the answer without starting or stopping the check, so "off"
    would not hold until a restart. Only the dedicated route may change it."""
    client, bm = open_client
    monkeypatch.setattr(
        "backend.core.update_service.fetch_latest",
        lambda method: UpdateProbe(source=method, latest_version="1.0.0"),
    )
    client.put("/api/updates/consent", json={"enabled": True})
    refused = client.put(
        "/api/system/app-config/updates.check_enabled", json={"value": False}
    ).json()
    assert refused == {"success": False, "error": "key_not_allowed"}
    assert client.get("/api/updates/state").json()["consent"] is True
    assert bm.update_service.running() is True
    _run(bm.update_service.stop())


# --- authentication -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("GET", "/api/updates/changelog", None),
        ("GET", "/api/updates/state", None),
        ("POST", "/api/updates/check", None),
        ("PUT", "/api/updates/consent", {"enabled": True}),
    ],
)
def test_every_update_route_requires_a_session(open_client, monkeypatch, method, path, body):
    client, bm = open_client
    monkeypatch.setattr(
        "backend.core.update_service.fetch_latest",
        lambda m: (_ for _ in ()).throw(AssertionError("an anonymous caller reached the network")),
    )
    _run(bm.auth.set_auth_enabled(True))
    try:
        client.cookies.clear()
        response = client.request(method, path, json=body)
    finally:
        _run(bm.auth.set_auth_enabled(False))
    assert response.status_code == 401
    assert _run(bm.db.get_config("updates.check_enabled")) == "false"
