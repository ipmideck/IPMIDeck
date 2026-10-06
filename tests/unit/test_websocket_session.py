"""Origin checking and lifetime revalidation of the telemetry WebSocket."""

from __future__ import annotations

import time

import pytest
from starlette.websockets import WebSocketDisconnect

import backend.main as bm
from backend.main import _ws_origin_allowed


class _Headers(dict):
    def get(self, key, default=None):  # header lookup is case-insensitive
        return super().get(key.lower(), default)


class _FakeWS:
    def __init__(self, **headers):
        self.headers = _Headers({k.lower(): v for k, v in headers.items()})


def test_a_handshake_from_this_app_is_allowed():
    assert _ws_origin_allowed(
        _FakeWS(origin="http://192.0.2.10:3000", host="192.0.2.10:3000")
    ) is True


def test_a_handshake_from_another_site_is_refused():
    """Any page the operator visits can open a socket here carrying their cookie."""
    assert _ws_origin_allowed(
        _FakeWS(origin="http://evil.example", host="192.0.2.10:3000")
    ) is False


def test_a_different_port_on_the_same_host_is_refused():
    """Cookies are shared across ports, so another local service is a real origin."""
    assert _ws_origin_allowed(
        _FakeWS(origin="http://192.0.2.10:9999", host="192.0.2.10:3000")
    ) is False


def test_the_scheme_does_not_have_to_match():
    """Behind a TLS-terminating proxy the app sees plain http for an https page."""
    assert _ws_origin_allowed(
        _FakeWS(origin="https://192.0.2.10:3000", host="192.0.2.10:3000")
    ) is True


def test_a_request_without_an_origin_is_allowed():
    """Command-line clients and health checks send none; browsers always do."""
    assert _ws_origin_allowed(_FakeWS(host="192.0.2.10:3000")) is True


def test_a_null_origin_is_refused():
    """Sandboxed frames and file:// pages send this; none of them is the dashboard."""
    assert _ws_origin_allowed(_FakeWS(origin="null", host="192.0.2.10:3000")) is False


def test_a_rewritten_host_refuses_the_handshake_without_the_escape_hatch(monkeypatch):
    """The nginx default. Without a way out the dashboard loads but shows no live data."""
    monkeypatch.setattr(bm.config.server, "trusted_origins", [])
    assert _ws_origin_allowed(
        _FakeWS(origin="https://ipmi.example.com", host="localhost:3000")
    ) is False


def test_a_trusted_origin_is_allowed_through_a_rewritten_host(monkeypatch):
    """The same setting the HTTP guard reads, so it is configured once."""
    monkeypatch.setattr(bm.config.server, "trusted_origins", ["https://ipmi.example.com"])
    assert _ws_origin_allowed(
        _FakeWS(origin="https://ipmi.example.com", host="localhost:3000")
    ) is True


def test_the_escape_hatch_admits_only_what_is_listed_on_the_socket(monkeypatch):
    monkeypatch.setattr(bm.config.server, "trusted_origins", ["https://ipmi.example.com"])
    assert _ws_origin_allowed(
        _FakeWS(origin="http://evil.example", host="localhost:3000")
    ) is False


def test_the_socket_is_refused_without_a_session(client_auth):
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client_auth.websocket_connect("/ws"):
            pass
    assert excinfo.value.code == 1008


def test_a_foreign_origin_is_refused_over_a_real_handshake(client):
    """Auth is OFF here on purpose: that is when a cross-site socket costs the most."""
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/ws", headers={"origin": "http://evil.example"}):
            pass
    assert excinfo.value.code == 1008


def test_a_socket_is_accepted_without_auth(client):
    with client.websocket_connect("/ws") as ws:
        assert ws is not None


def test_revalidation_happens_often_enough_to_matter():
    """The interval IS the eviction latency after a password change — keep it honest."""
    assert 0 < bm._WS_REVALIDATE_SECONDS <= 60


def test_a_malformed_origin_refuses_the_handshake_instead_of_raising(client):
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/ws", headers={"origin": "http://[::1"}):
            pass
    assert excinfo.value.code == 1008


def test_an_open_socket_is_closed_once_its_session_is_revoked(client_auth, monkeypatch):
    """The in-loop re-check, not just the handshake: rewriting the account invalidates every
    token issued before it, and the socket opened with one of them must then be closed.

    Observed on the server side (the connection leaves the manager when the loop ends)
    rather than by reading from the client, whose receive has no timeout: a regression
    must fail this test, not hang it.
    """
    monkeypatch.setattr(bm, "_WS_REVALIDATE_SECONDS", 0.05)
    client_auth.post("/api/auth/setup", json={"username": "admin", "password": "correcthorse"})

    def _open_sockets() -> int:
        return len(bm.ws_manager._connections)

    def _wait_for(predicate) -> bool:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.02)
        return False

    with client_auth.websocket_connect("/ws"):
        assert _wait_for(lambda: _open_sockets() == 1)
        rewrite = client_auth.post(
            "/api/auth/configure",
            json={"username": "admin", "password": "newhorse1", "current_password": "correcthorse"},
        )
        assert rewrite.json()["success"] is True
        closed = _wait_for(lambda: _open_sockets() == 0)
    assert closed, "the socket outlived the session that opened it"
