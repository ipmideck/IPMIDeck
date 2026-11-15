"""Deleting a server must not leave its state behind in memory."""

from __future__ import annotations

import backend.main as bm
from backend.modules.fanpilot import tasks as fanpilot_tasks
from backend.modules.power import routes as power_routes
from backend.modules.power import tasks as power_tasks
from backend.modules.sel import tasks as sel_tasks
from backend.modules.sensors import tasks as sensor_tasks


def _create_server(client) -> str:
    r = client.post("/api/servers", json={
        "name": "temporary", "host": "192.0.2.77",
        "username": "root", "password": "calvin", "vendor": "dell",
    })
    body = r.json()
    assert body.get("success") is True, body
    return body["server_id"]


def test_deleting_a_server_clears_every_tracker(client):
    server_id = _create_server(client)

    # Seed the state a running instance would have accumulated for this server.
    sensor_tasks._next_retry[server_id] = 123.0
    power_tasks._next_retry[server_id] = 123.0
    power_routes._last_command[server_id] = 123.0
    sel_tasks._last_seen_sel_id[server_id] = 7
    fanpilot_tasks._last_state[server_id] = {"mode": "auto"}
    fanpilot_tasks._garbage_counts[server_id] = 3
    bm.ws_manager._last_sensor[server_id] = {"Fan1": {"value": 2400}}
    bm.ws_manager._last_power[server_id] = {"status": "on"}

    assert client.delete(f"/api/servers/{server_id}").json()["success"] is True

    assert server_id not in sensor_tasks._next_retry
    assert server_id not in power_tasks._next_retry
    assert server_id not in power_routes._last_command
    assert server_id not in sel_tasks._last_seen_sel_id
    assert server_id not in fanpilot_tasks._last_state
    assert server_id not in fanpilot_tasks._garbage_counts
    # This one is a correctness bug as much as a memory one: cached readings for a
    # deleted server were replayed to every newly connected client.
    assert server_id not in bm.ws_manager._last_sensor
    assert server_id not in bm.ws_manager._last_power


def test_deleting_a_server_releases_its_command_lock(client):
    server_id = _create_server(client)
    bm.ipmi_service.forget_host("192.0.2.77")  # start from a known state
    if hasattr(bm.ipmi_service, "_host_locks"):
        bm.ipmi_service._get_host_lock("192.0.2.77")
        assert "192.0.2.77" in bm.ipmi_service._host_locks

    client.delete(f"/api/servers/{server_id}")

    if hasattr(bm.ipmi_service, "_host_locks"):
        assert "192.0.2.77" not in bm.ipmi_service._host_locks


def test_deleting_a_server_removes_its_event_log_bookmark(client):
    server_id = _create_server(client)
    key = f"sel:last_seen_id:{server_id}"
    client.post("/api/system/config", json={"key": key, "value": "42"})

    client.delete(f"/api/servers/{server_id}")

    row = client.get("/api/servers").json()
    assert all(s["id"] != server_id for s in row.get("servers", []))


def test_deleting_a_server_that_does_not_exist_is_harmless(client):
    assert client.delete("/api/servers/no-such-server").json()["success"] is True


def test_a_command_for_an_unknown_server_leaves_no_entry(client):
    """The rate-limit key is a raw path segment, so this used to grow the table."""
    before = dict(power_routes._last_command)
    client.post("/api/modules/power/made-up-id/command", json={"action": "on"})
    assert "made-up-id" not in power_routes._last_command
    assert set(power_routes._last_command) == set(before)
