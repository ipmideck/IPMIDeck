"""The export endpoints actually apply the sanitisation, not just the helpers in isolation.

tests/unit/test_csv_export.py proves ``csv_safe`` and ``safe_filename_part`` behave. That is
not the same as proving the routes call them: deleting both calls from the SEL export left
the whole suite green, because every existing test exercised the helpers as pure functions.
These tests drive the real endpoint end to end, so removing a call fails here.

The SEL path is the one that matters most. Event descriptions and sensor names are reproduced
verbatim from the BMC's own event log — the untrusted source the sanitisation exists for.
"""

from __future__ import annotations

import asyncio
import csv
import io

import backend.main as bm

# A cell a spreadsheet evaluates on open. The DDE form is the one that reaches a shell.
FORMULA_DESCRIPTION = '=cmd|\' /c calc\'!A1'


def _seed_sel_row(server_id: str, **overrides) -> None:
    """Insert one SEL cache row on the live lifespan DB, as the poller would."""
    row = {
        "event_id": "0x0001",
        "timestamp": "2026-01-01 00:00:00",
        "sensor_name": "Temp",
        "event_type": "Threshold",
        "description": "Upper Critical going high",
        "severity": "critical",
    }
    row.update(overrides)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        bm.db.execute(
            "INSERT INTO sel_cache "
            "(server_id, event_id, timestamp, sensor_name, event_type, description, severity) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                server_id,
                row["event_id"],
                row["timestamp"],
                row["sensor_name"],
                row["event_type"],
                row["description"],
                row["severity"],
            ),
        )
    )
    loop.run_until_complete(bm.db.commit())


def _new_server(client) -> str:
    resp = client.post(
        "/api/servers",
        json={
            "name": "Demo",
            "host": "192.0.2.10",
            "username": "demo",
            "password": "demo",
            "vendor": "dell",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["server_id"]


def test_sel_csv_export_neutralises_a_formula_description(client):
    """A BMC-supplied description that opens as a formula is exported as text."""
    server_id = _new_server(client)
    _seed_sel_row(server_id, description=FORMULA_DESCRIPTION)

    resp = client.get(f"/api/modules/sel/{server_id}/export?format=csv")
    assert resp.status_code == 200, resp.text

    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(rows) == 1, resp.text
    assert rows[0]["description"] == "'" + FORMULA_DESCRIPTION
    assert not rows[0]["description"].startswith(("=", "+", "-", "@"))


def test_sel_csv_export_neutralises_a_formula_sensor_name(client):
    """Sensor names come from the same untrusted log and get the same treatment."""
    server_id = _new_server(client)
    _seed_sel_row(server_id, sensor_name="@SUM(1+1)*cmd")

    resp = client.get(f"/api/modules/sel/{server_id}/export?format=csv")
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert rows[0]["sensor_name"] == "'@SUM(1+1)*cmd"


def test_sel_csv_export_leaves_ordinary_rows_readable(client):
    """Sanitising must not corrupt the ordinary case the operator actually reads."""
    server_id = _new_server(client)
    _seed_sel_row(server_id)

    resp = client.get(f"/api/modules/sel/{server_id}/export?format=csv")
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert rows[0]["description"] == "Upper Critical going high"
    assert rows[0]["sensor_name"] == "Temp"
    assert rows[0]["severity"] == "critical"


def test_sel_export_filename_cannot_steer_the_header(client):
    """The server id is echoed into Content-Disposition; it must not break the quoted string."""
    # Requested for an id that does not exist: the export still builds the header, which is
    # the part under test, and an unknown id simply yields no rows.
    resp = client.get('/api/modules/sel/a%22b%3Bc/export?format=csv')
    assert resp.status_code == 200, resp.text

    disposition = resp.headers["content-disposition"]
    assert disposition == 'attachment; filename=sel_a_b_c.csv', disposition
    assert '"' not in disposition
    assert disposition.count(";") == 1  # only the one separating the header's own parameters


def test_sel_json_export_filename_is_sanitised_too(client):
    """The JSON branch builds its own header and must not be the way around the guard."""
    resp = client.get('/api/modules/sel/a%22b%3Bc/export?format=json')
    assert resp.headers["content-disposition"] == 'attachment; filename=sel_a_b_c.json'


def test_history_csv_export_neutralises_a_formula_sensor_name(client):
    """The historical sensor export shares the helpers and must keep applying them."""
    server_id = _new_server(client)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        bm.db.execute(
            "INSERT INTO sensor_readings (server_id, sensor_name, sensor_type, value, unit) "
            "VALUES (?, ?, ?, ?, ?)",
            (server_id, "=HYPERLINK(0)", "temperature", 40.0, "C"),
        )
    )
    loop.run_until_complete(bm.db.commit())

    resp = client.get(
        f"/api/system/history-csv?server_id={server_id}&sensor_name=%3DHYPERLINK(0)"
    )
    assert resp.status_code == 200, resp.text
    assert "'=HYPERLINK(0)" in resp.text
    # The same value reaches the filename, where a formula prefix is harmless but the
    # punctuation is not.
    assert resp.headers["content-disposition"] == (
        'attachment; filename="ipmideck-_HYPERLINK_0_-24h.csv"'
    )
