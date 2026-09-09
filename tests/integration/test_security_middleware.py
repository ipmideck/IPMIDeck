"""The cross-origin guard and the defensive response headers, exercised through the app.

Both are `@app.middleware("http")` functions, so nothing short of a real request proves they
are installed: they shipped with no test at all, and an accidental removal of either
decorator would have been invisible.

The guard is also the change most able to break a working deployment. Behind a reverse proxy
that rewrites Host — nginx does not preserve it unless configured to — the browser's Origin
can never match, so every write would be refused. `server.trusted_origins` is the way out,
and the tests below pin both that it works and that it opens nothing else.
"""

from __future__ import annotations

import backend.main as bm

FOREIGN = "http://evil.example.com"

CREATE_SERVER = {
    "name": "Demo",
    "host": "192.0.2.10",
    "username": "demo",
    "password": "demo",
    "vendor": "dell",
}


def _is_rejected(resp) -> bool:
    return resp.status_code == 403 and resp.json().get("error") == "Cross-origin request rejected"


# --- the guard rejects what it should -------------------------------------------------------


def test_post_from_a_foreign_origin_is_rejected(client):
    resp = client.post("/api/servers", json=CREATE_SERVER, headers={"Origin": FOREIGN})
    assert _is_rejected(resp), resp.text


def test_referer_alone_is_enough_to_reject(client):
    """Origin is absent on some form posts; Referer carries the same signal."""
    resp = client.post(
        "/api/servers", json=CREATE_SERVER, headers={"Referer": f"{FOREIGN}/dashboard"}
    )
    assert _is_rejected(resp), resp.text


def test_another_port_on_the_same_host_is_rejected(client):
    """Cookies are shared across ports, so a neighbouring service is a real attacker here."""
    resp = client.post(
        "/api/servers", json=CREATE_SERVER, headers={"Origin": "http://testserver:9999"}
    )
    assert _is_rejected(resp), resp.text


def test_the_guard_runs_before_routing(client):
    """A rejected request never reaches a handler — proven by a path that has none."""
    resp = client.post("/api/no-such-endpoint", headers={"Origin": FOREIGN})
    assert _is_rejected(resp), resp.text


def test_every_state_changing_method_is_guarded(client):
    for method in ("post", "put", "patch", "delete"):
        resp = getattr(client, method)("/api/no-such-endpoint", headers={"Origin": FOREIGN})
        assert _is_rejected(resp), f"{method}: {resp.text}"


# --- the guard allows what it must ----------------------------------------------------------


def test_a_matching_origin_passes(client):
    resp = client.post("/api/servers", json=CREATE_SERVER, headers={"Origin": "http://testserver"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True


def test_a_request_with_no_origin_passes(client):
    """Command-line clients, the container health check and integrations send neither header."""
    resp = client.post("/api/servers", json=CREATE_SERVER)
    assert resp.status_code == 200, resp.text


def test_a_foreign_origin_on_a_read_is_not_blocked(client):
    """A cross-origin GET cannot be turned into a write, and blocking it would break links."""
    resp = client.get("/api/servers", headers={"Origin": FOREIGN})
    assert resp.status_code == 200, resp.text


# --- the proxy escape hatch -----------------------------------------------------------------


def test_a_rewritten_host_refuses_writes_without_the_escape_hatch(client):
    """The nginx default: the browser says ipmi.example.com, the app is told localhost:3000."""
    resp = client.post(
        "/api/servers",
        json=CREATE_SERVER,
        headers={"Origin": "https://ipmi.example.com", "Host": "localhost:3000"},
    )
    assert _is_rejected(resp), resp.text


def test_listing_the_external_origin_restores_writes(client, monkeypatch):
    monkeypatch.setattr(bm.config.server, "trusted_origins", ["https://ipmi.example.com"])
    resp = client.post(
        "/api/servers",
        json=CREATE_SERVER,
        headers={"Origin": "https://ipmi.example.com", "Host": "localhost:3000"},
    )
    assert resp.status_code == 200, resp.text


def test_the_escape_hatch_admits_only_what_is_listed(client, monkeypatch):
    """Configuring one external origin must not turn the guard off for every other one."""
    monkeypatch.setattr(bm.config.server, "trusted_origins", ["https://ipmi.example.com"])
    resp = client.post("/api/servers", json=CREATE_SERVER, headers={"Origin": FOREIGN})
    assert _is_rejected(resp), resp.text


def test_a_listed_https_origin_does_not_trust_its_cleartext_twin(client, monkeypatch):
    """An operator who wrote https means https; downgrading is the attacker's move."""
    monkeypatch.setattr(bm.config.server, "trusted_origins", ["https://ipmi.example.com"])
    resp = client.post(
        "/api/servers",
        json=CREATE_SERVER,
        headers={"Origin": "http://ipmi.example.com", "Host": "localhost:3000"},
    )
    assert _is_rejected(resp), resp.text


# --- defensive response headers -------------------------------------------------------------


def test_defensive_headers_are_on_an_api_response(client):
    resp = client.get("/api/health")
    assert resp.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["referrer-policy"] == "no-referrer"


def test_defensive_headers_are_on_an_error_response(client):
    """A 404 is still a response a hostile page can frame."""
    resp = client.get("/api/no-such-endpoint")
    assert resp.status_code == 404
    assert resp.headers["x-frame-options"] == "DENY"


def test_hsts_is_absent_over_plain_http(client):
    """Sent over http it is ignored anyway; honoured on a LAN name it would strand the operator."""
    assert "strict-transport-security" not in client.get("/api/health").headers


def test_hsts_is_sent_over_https(client):
    resp = client.get("https://testserver/api/health")
    assert resp.headers["strict-transport-security"] == "max-age=31536000"
