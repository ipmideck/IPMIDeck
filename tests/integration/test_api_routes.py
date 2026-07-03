"""API integration tests (TEST-04) — FastAPI TestClient against the real ASGI stack.

These tests drive backend.main.app through its real lifespan over an ISOLATED temp SQLite
DB in demo mode (no production data/ipmideck.db, no ipmitool, no real BMC — RESEARCH Pitfall 3).
They use the conftest harness fixtures (03-01):

  * client_auth — auth ENABLED (DB default auth_enabled="true"): the genuine guarded-route
    fixture used for the 401 -> setup -> 200 flow AND the localized login-failure test.
  * client      — auth DISABLED via bm.auth.set_auth_enabled(False) AFTER lifespan (REVIEWS
    HIGH #1: IPMIDECK_AUTH_ENABLED is INERT for the runtime gate, which reads the DB). With
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

import asyncio

import backend.main as bm
from backend.core.database import Database
from backend.core.i18n import t
from backend.core.ipmi_service import FanWriteResult


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
    (HIGH #1); under auth-ON these guarded routes would 401. No request reaches data/ipmideck.db
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


# --- quick-260625-rw5: host-field validation on create + update -----------------------------


def test_create_server_rejects_url_host(client):
    """A URL host (the app's own web-UI URL) is rejected BEFORE the DB write — never inserted."""
    resp = client.post(
        "/api/servers",
        json={
            "name": "Bad URL host",
            "host": "http://127.0.0.1:8080/",
            "username": "root",
            "password": "calvin",
            "vendor": "dell",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is False
    assert body["error"] == t("invalid_host", "en")

    # The rejected create must not have inserted a row with that host.
    list_resp = client.get("/api/servers")
    assert list_resp.status_code == 200
    hosts = [s["host"] for s in list_resp.json()["servers"]]
    assert "http://127.0.0.1:8080/" not in hosts


def test_create_server_accepts_valid_ip_and_hostname(client):
    """A bare IPv4 and a plain hostname both pass validation and are created."""
    ip_resp = client.post(
        "/api/servers",
        json={
            "name": "Valid IP",
            "host": "192.0.2.40",
            "username": "root",
            "password": "calvin",
            "vendor": "dell",
        },
    )
    assert ip_resp.status_code == 200, ip_resp.text
    assert ip_resp.json()["success"] is True

    name_resp = client.post(
        "/api/servers",
        json={
            "name": "Valid hostname",
            "host": "bmc.example.com",
            "username": "root",
            "password": "calvin",
            "vendor": "dell",
        },
    )
    assert name_resp.status_code == 200, name_resp.text
    assert name_resp.json()["success"] is True


def test_create_server_rejects_empty_host(client):
    """An empty host is rejected with the localized invalid_host error."""
    resp = client.post(
        "/api/servers",
        json={
            "name": "Empty host",
            "host": "",
            "username": "root",
            "password": "calvin",
            "vendor": "dell",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is False
    assert body["error"] == t("invalid_host", "en")


def test_create_server_invalid_host_localized(client):
    """The invalid_host rejection honors Accept-Language (it != en), proving it is i18n-keyed."""
    resp = client.post(
        "/api/servers",
        json={
            "name": "Localized reject",
            "host": "http://127.0.0.1:8080/",
            "username": "root",
            "password": "calvin",
            "vendor": "dell",
        },
        headers={"Accept-Language": "it"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is False
    assert body["error"] == t("invalid_host", "it")
    assert body["error"] == "Indirizzo host non valido"
    assert body["error"] != t("invalid_host", "en")


def test_update_server_rejects_invalid_host(client):
    """PUT with an invalid host is rejected with the localized invalid_host error."""
    create_resp = client.post(
        "/api/servers",
        json={
            "name": "To update",
            "host": "192.0.2.41",
            "username": "root",
            "password": "calvin",
            "vendor": "dell",
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    server_id = create_resp.json()["server_id"]

    update_resp = client.put(
        f"/api/servers/{server_id}",
        json={"host": "http://127.0.0.1:8080/"},
    )
    assert update_resp.status_code == 200, update_resp.text
    body = update_resp.json()
    assert body["success"] is False
    assert body["error"] == t("invalid_host", "en")


def test_update_server_without_host_succeeds(client):
    """PUT that OMITS host skips host validation — the update applies, host unchanged."""
    create_resp = client.post(
        "/api/servers",
        json={
            "name": "Original name",
            "host": "192.0.2.42",
            "username": "root",
            "password": "calvin",
            "vendor": "dell",
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    server_id = create_resp.json()["server_id"]

    update_resp = client.put(f"/api/servers/{server_id}", json={"name": "Renamed"})
    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json()["success"] is True

    list_resp = client.get("/api/servers")
    assert list_resp.status_code == 200
    match = [s for s in list_resp.json()["servers"] if s["id"] == server_id]
    assert len(match) == 1
    assert match[0]["name"] == "Renamed"
    assert match[0]["host"] == "192.0.2.42"


# --- 08-01 (D-12): strict vendor enum -> automatic 422 at the parse layer -------------------


def test_create_server_rejects_unknown_vendor(client):
    """POST with a non-enum vendor is rejected with a Pydantic 422 (parse-layer), not a 200.

    The Literal[...] on ServerCreate.vendor raises BEFORE create_server's body runs, so the
    response is a genuine HTTP 422 — never a 200 with {"success": False}. RFC5737 host only.
    """
    resp = client.post(
        "/api/servers",
        json={
            "name": "Bad vendor",
            "host": "192.0.2.60",
            "username": "root",
            "password": "calvin",
            "vendor": "acme",
        },
    )
    assert resp.status_code == 422, resp.text

    # The rejected create must not have inserted a row with that host.
    list_resp = client.get("/api/servers")
    assert list_resp.status_code == 200
    hosts = [s["host"] for s in list_resp.json()["servers"]]
    assert "192.0.2.60" not in hosts


def test_update_server_rejects_unknown_vendor(client):
    """Create a valid server, then PUT a non-enum vendor -> 422 (parse-layer rejection)."""
    create_resp = client.post(
        "/api/servers",
        json={
            "name": "Vendor edit",
            "host": "192.0.2.61",
            "username": "root",
            "password": "calvin",
            "vendor": "dell",
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    server_id = create_resp.json()["server_id"]

    update_resp = client.put(f"/api/servers/{server_id}", json={"vendor": "acme"})
    assert update_resp.status_code == 422, update_resp.text

    # The invalid PUT left the stored vendor unchanged (still 'dell').
    get_resp = client.get(f"/api/servers/{server_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["server"]["vendor"] == "dell"


def test_update_server_without_vendor_ok(client):
    """PUT that OMITS vendor is accepted (not 422) and leaves the stored vendor unchanged.

    Pitfall 8: vendor stays Optional, so exclude_unset semantics keep an omitted vendor intact.
    """
    create_resp = client.post(
        "/api/servers",
        json={
            "name": "Keep vendor",
            "host": "192.0.2.62",
            "username": "root",
            "password": "calvin",
            "vendor": "supermicro",
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    server_id = create_resp.json()["server_id"]

    update_resp = client.put(f"/api/servers/{server_id}", json={"name": "Renamed only"})
    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json()["success"] is True

    get_resp = client.get(f"/api/servers/{server_id}")
    assert get_resp.status_code == 200
    server = get_resp.json()["server"]
    assert server["name"] == "Renamed only"
    assert server["vendor"] == "supermicro"  # unchanged


def test_create_server_accepts_new_vendors(client):
    """POST with the two NEW enum values (lenovo, ibm) succeeds — proves the enum accepts them."""
    lenovo_resp = client.post(
        "/api/servers",
        json={
            "name": "Lenovo XCC",
            "host": "192.0.2.63",
            "username": "root",
            "password": "calvin",
            "vendor": "lenovo",
        },
    )
    assert lenovo_resp.status_code == 200, lenovo_resp.text
    assert lenovo_resp.json()["success"] is True

    ibm_resp = client.post(
        "/api/servers",
        json={
            "name": "IBM IMM",
            "host": "192.0.2.64",
            "username": "root",
            "password": "calvin",
            "vendor": "ibm",
        },
    )
    assert ibm_resp.status_code == 200, ibm_resp.text
    assert ibm_resp.json()["success"] is True


# --- 05-02 (P0-3): /mode route success-honesty -------------------------------------------


def _create_demo_server(client) -> str:
    """Create a server through the auth-OFF client and return its id."""
    resp = client.post(
        "/api/servers",
        json={
            "name": "Mode R720",
            "host": "192.0.2.50",
            "username": "root",
            "password": "calvin",
            "vendor": "dell",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["server_id"]


def _latest_log_result(client, server_id: str) -> str | None:
    """Return the `result` of the most recent command_log row for a server via /api/logs."""
    logs_resp = client.get(f"/api/logs?server_id={server_id}")
    assert logs_resp.status_code == 200, logs_resp.text
    rows = logs_resp.json()["logs"]
    return rows[0]["result"] if rows else None


def test_mode_manual_success_writes_success(client):
    """A manual /mode write that the demo BMC accepts -> success:true + command_log 'success'."""
    server_id = _create_demo_server(client)
    resp = client.post(
        f"/api/modules/fanpilot/{server_id}/mode",
        json={"mode": "manual", "speed": 60},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["mode"] == "manual"
    assert _latest_log_result(client, server_id) == "success"


def test_mode_manual_rejected_returns_false_and_logs_rejected(client, monkeypatch):
    """A manual /mode write the BMC REJECTS -> success:false + command_log 'rejected' (not 'success').

    Monkeypatch the live demo IPMI service so set_fan_speed returns a rejected FanWriteResult
    (0xd4). The route must inspect .ok, return success:false, and log result='rejected'.
    """
    server_id = _create_demo_server(client)

    async def _rejected_speed(host, user, password, speed_pct, vendor="dell"):
        return FanWriteResult(
            False, "rejected", "d4", "rsp=0xd4: Insufficient privilege level"
        )

    # bm.ipmi_service is the live DemoIPMIService injected into the ModuleContext.
    monkeypatch.setattr(bm.ipmi_service, "set_fan_speed", _rejected_speed)

    resp = client.post(
        f"/api/modules/fanpilot/{server_id}/mode",
        json={"mode": "manual", "speed": 60},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is False, "route must NOT report success on a rejected write"
    assert body["mode"] == "manual"
    assert "error" in body
    assert _latest_log_result(client, server_id) == "rejected"


# --- 05-03 (SR / FANPILOT-RESUME-STATE): migration columns + /mode intent persistence ------


def _server_intent(client, server_id: str) -> dict:
    """Read fan_desired_mode / fan_desired_speed for a server off the live lifespan DB.

    The new SR columns aren't surfaced by the list/get server routes (they SELECT a fixed
    column set), so we read them directly from bm.db (live during the TestClient lifespan,
    same pattern conftest uses with bm.auth). Proves both that the columns EXIST and that
    /mode persisted the right intent.
    """
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(
        bm.db.fetchone(
            "SELECT fan_desired_mode, fan_desired_speed FROM servers WHERE id = ?",
            (server_id,),
        )
    )


def test_servers_schema_has_fan_desired_columns(client):
    """The guarded ALTER added fan_desired_mode + fan_desired_speed to the servers table.

    PRAGMA table_info(servers) lists both columns after the lifespan-driven connect().
    """
    loop = asyncio.get_event_loop()
    cols = loop.run_until_complete(bm.db.fetchall("PRAGMA table_info(servers)"))
    names = {c["name"] for c in cols}
    assert "fan_desired_mode" in names, "migration must add fan_desired_mode to servers"
    assert "fan_desired_speed" in names, "migration must add fan_desired_speed to servers"


def test_servers_migration_is_idempotent(tmp_path):
    """Calling Database.connect() twice on the SAME file must not raise (guarded ALTER).

    Mirrors the lifespan re-entering connect() per TestClient over the same temp DB.
    """

    async def _twice() -> None:
        db_path = str(tmp_path / "idempotent.db")
        db1 = Database(db_path)
        await db1.connect()  # creates schema + runs the ALTERs (columns now present)
        await db1.close()
        db2 = Database(db_path)
        await db2.connect()  # ALTERs must be swallowed as duplicate-column, NOT raise
        cols = await db2.fetchall("PRAGMA table_info(servers)")
        names = {c["name"] for c in cols}
        assert "fan_desired_mode" in names
        assert "fan_desired_speed" in names
        await db2.close()

    asyncio.new_event_loop().run_until_complete(_twice())


def test_mode_manual_persists_intent(client):
    """POST /mode {manual, speed:100} persists fan_desired_mode='manual' + fan_desired_speed=100."""
    server_id = _create_demo_server(client)
    resp = client.post(
        f"/api/modules/fanpilot/{server_id}/mode",
        json={"mode": "manual", "speed": 100},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True
    intent = _server_intent(client, server_id)
    assert intent["fan_desired_mode"] == "manual"
    assert intent["fan_desired_speed"] == 100


def test_mode_fanpilot_persists_intent(client):
    """POST /mode {fanpilot, profile_id} persists fan_desired_mode='fanpilot'."""
    server_id = _create_demo_server(client)
    # A preset profile id=1 exists from the fanpilot module migration seed.
    resp = client.post(
        f"/api/modules/fanpilot/{server_id}/mode",
        json={"mode": "fanpilot", "profile_id": 1},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True
    intent = _server_intent(client, server_id)
    assert intent["fan_desired_mode"] == "fanpilot"
    # fanpilot leaves speed NULL — fanpilot_profile_id already captures the profile.
    assert intent["fan_desired_speed"] is None


def test_mode_auto_persists_intent_and_clears_speed(client):
    """POST /mode {auto} persists fan_desired_mode='auto' and clears fan_desired_speed (NULL)."""
    server_id = _create_demo_server(client)
    # First pin manual @ 80 so there's a speed to clear.
    client.post(
        f"/api/modules/fanpilot/{server_id}/mode",
        json={"mode": "manual", "speed": 80},
    )
    resp = client.post(
        f"/api/modules/fanpilot/{server_id}/mode",
        json={"mode": "auto"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True
    intent = _server_intent(client, server_id)
    assert intent["fan_desired_mode"] == "auto"
    assert intent["fan_desired_speed"] is None


# --- 08-04 (D-17): demo vendor-aware argv echo -> command_log (hardware-free routing proof) --


def _create_server(client, vendor: str, host: str) -> str:
    """Create a server of a given vendor through the auth-OFF client and return its id."""
    resp = client.post(
        "/api/servers",
        json={
            "name": f"Demo {vendor}",
            "host": host,
            "username": "demo",
            "password": "demo",
            "vendor": vendor,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["server_id"]


def _latest_log_text(client, server_id: str) -> str:
    """Return the newest command_log row's command_detail + error_message joined, via /api/logs."""
    logs_resp = client.get(f"/api/logs?server_id={server_id}")
    assert logs_resp.status_code == 200, logs_resp.text
    rows = logs_resp.json()["logs"]
    assert rows, "expected at least one command_log row for the server"
    row = rows[0]
    return " ".join(str(row.get(k) or "") for k in ("command_detail", "error_message"))


def test_demo_supermicro_write_echoes_argv_to_command_log(client):
    """A demo supermicro manual /mode write records the both-zone 0x30 0x70 0x66 argv in command_log.

    Proves per-vendor routing is assertable via GET /api/logs WITHOUT hardware: the vendor-aware
    DemoIPMIService computes the would-be ipmitool argv through the shared build_fan_argv() and the
    /mode route persists it into the command_log row (D-17).
    """
    server_id = _create_server(client, "supermicro", "192.0.2.71")
    resp = client.post(
        f"/api/modules/fanpilot/{server_id}/mode",
        json={"mode": "manual", "speed": 50},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True
    detail = _latest_log_text(client, server_id)
    assert "0x30 0x70 0x66" in detail, detail


def test_demo_hpe_write_records_no_fan_argv(client):
    """A demo hpe (monitoring-only) /mode write is unsupported — NO fan argv (0x..) recorded.

    hpe has no IPMI fan control (VendorProfile fan_capable=False), so the demo service returns an
    'unsupported' result, the route reports success:false, and the command_log row carries the
    honest 'not supported' message — never a per-vendor raw argv.
    """
    server_id = _create_server(client, "hpe", "192.0.2.72")
    resp = client.post(
        f"/api/modules/fanpilot/{server_id}/mode",
        json={"mode": "manual", "speed": 50},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is False  # monitoring-only vendor -> unsupported write
    detail = _latest_log_text(client, server_id)
    assert "0x70" not in detail
    assert "0x30 0x70 0x66" not in detail


def test_demo_dell_write_echoes_argv_to_command_log(client):
    """A demo dell manual /mode write records the Dell 0x30 0x30 0x02 0xff speed argv (D-17)."""
    server_id = _create_server(client, "dell", "192.0.2.73")
    resp = client.post(
        f"/api/modules/fanpilot/{server_id}/mode",
        json={"mode": "manual", "speed": 50},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True
    detail = _latest_log_text(client, server_id)
    assert "0x30 0x30 0x02 0xff" in detail, detail
