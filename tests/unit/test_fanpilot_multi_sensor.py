"""A fan profile can follow several temperature sensors, combined as the hottest or the mean.

Covers the pieces that make that safe:

  * the helpers that clean a sensor list, read a stored profile row and combine readings;
  * the engine's safety override, which trips on the hottest sensor even when the curve
    follows the average;
  * the module migration that adds the two columns, on a fresh database and on one that
    already ran the first migration (existing rows are not rewritten);
  * the profile API: new bodies, old single-sensor bodies, invalid input refused with 422
    and nothing stored, responses always carrying the normalised list;
  * the control loop: max and average aggregation, the safety override in average mode, and
    the existing fail-safe firing when any one selected sensor is missing, stale or reads an
    implausible value, with that sensor named in the alert.

Synthetic sensor names and the RFC5737 host 192.0.2.10 only.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from backend.core.database import Database
from backend.modules import get_ctx
from backend.modules.fanpilot import tasks as fp_tasks
from backend.modules.fanpilot.engine import (
    MAX_SOURCE_SENSORS,
    FanPilotController,
    clean_sensor_names,
    combine_temps,
    normalize_profile_sensors,
)
from tests.unit.test_fanpilot_failsafe import _drive_loop, _loop_server_row

PROFILES = "/api/modules/fanpilot/profiles"
MIGRATIONS = (
    Path(__file__).resolve().parents[2] / "backend" / "modules" / "fanpilot" / "migrations"
)
CURVE = [{"temp": 30, "speed": 20}, {"temp": 80, "speed": 100}]


# === clean_sensor_names ===


def test_clean_sensor_names_trims_and_keeps_order():
    assert clean_sensor_names([" CPU 1 ", "CPU 2"]) == ["CPU 1", "CPU 2"]


def test_clean_sensor_names_accepts_the_maximum():
    names = [f"Temp {i}" for i in range(MAX_SOURCE_SENSORS)]
    assert MAX_SOURCE_SENSORS == 8
    assert clean_sensor_names(names) == names


@pytest.mark.parametrize(
    "bad",
    [
        "CPU 1",
        None,
        {"a": 1},
        [],
        [f"Temp {i}" for i in range(9)],
        ["CPU 1", 5],
        ["CPU 1", "   "],
        ["x" * 65],
        ["CPU 1", " CPU 1 "],
    ],
)
def test_clean_sensor_names_rejects(bad):
    assert clean_sensor_names(bad) is None


def test_clean_sensor_names_allows_a_64_character_name_after_trimming():
    assert clean_sensor_names(["  " + "x" * 64 + " "]) == ["x" * 64]


# === normalize_profile_sensors ===


@pytest.mark.parametrize(
    "stored",
    [None, "not json", "[]", '{"a": 1}', '["CPU 1", 5]', json.dumps([f"T{i}" for i in range(9)])],
)
def test_normalize_falls_back_to_the_single_sensor(stored):
    row = {"source_sensor": "CPU 1", "source_sensors": stored, "sensor_mode": "avg"}
    assert normalize_profile_sensors(row) == (["CPU 1"], "avg")


def test_normalize_missing_key_is_the_single_sensor():
    assert normalize_profile_sensors({"source_sensor": "CPU 1"}) == (["CPU 1"], "max")


def test_normalize_without_any_sensor_uses_the_default():
    row = {"source_sensor": None, "source_sensors": None, "sensor_mode": None}
    assert normalize_profile_sensors(row) == (["CPU Temp"], "max")


def test_normalize_valid_list():
    row = {"source_sensor": "CPU 1", "source_sensors": '["CPU 1", "CPU 2"]', "sensor_mode": "max"}
    assert normalize_profile_sensors(row) == (["CPU 1", "CPU 2"], "max")


def test_normalize_list_edited_by_an_older_version_keeps_its_single_sensor():
    row = {"source_sensor": "CPU 2", "source_sensors": '["CPU 1", "CPU 2"]', "sensor_mode": "avg"}
    assert normalize_profile_sensors(row) == (["CPU 2"], "avg")


def test_normalize_list_that_is_not_already_clean_is_ignored():
    row = {"source_sensor": " CPU 1", "source_sensors": '[" CPU 1", "CPU 2"]'}
    assert normalize_profile_sensors(row) == ([" CPU 1"], "max")


@pytest.mark.parametrize("mode,expected", [("avg", "avg"), ("max", "max"), ("AVG", "max"),
                                           ("min", "max"), (None, "max")])
def test_normalize_mode(mode, expected):
    row = {"source_sensor": "CPU 1", "source_sensors": None, "sensor_mode": mode}
    assert normalize_profile_sensors(row)[1] == expected


def test_normalize_loop_row_without_the_new_keys():
    assert normalize_profile_sensors(_loop_server_row(vendor="dell")) == (["CPU Temp"], "max")


# === combine_temps ===


def test_combine_temps():
    assert combine_temps([40.0, 61.0], "max") == 61.0
    assert combine_temps([40.0, 61.0], "avg") == 50.5
    assert combine_temps([47.0], "max") == 47.0
    assert combine_temps([47.0], "avg") == 47.0


# === Engine: safety follows the hottest sensor ===


def test_safety_temp_trips_the_override_on_a_cool_average():
    ctrl = FanPilotController("srv", hysteresis=3.0, safety_threshold=85.0)
    assert ctrl.compute_fan_speed(CURVE, 50.0, safety_temp=90.0) == 100
    # Still inside the hysteresis band (>= 82): hold 100%.
    assert ctrl.compute_fan_speed(CURVE, 50.0, safety_temp=84.0) == 100
    # Below the band: released, back on the curve at the combined value.
    assert ctrl.compute_fan_speed(CURVE, 50.0, safety_temp=81.0) == 52


def test_without_safety_temp_the_result_is_unchanged():
    a = FanPilotController("a", hysteresis=3.0, safety_threshold=85.0)
    b = FanPilotController("b", hysteresis=3.0, safety_threshold=85.0)
    for temp in (40.0, 60.0, 86.0, 84.0, 80.0, 55.0):
        assert a.compute_fan_speed(CURVE, temp) == b.compute_fan_speed(
            CURVE, temp, safety_temp=temp
        )


# === Migration ===


async def _columns(db: Database) -> set[str]:
    rows = await db.fetchall("PRAGMA table_info(fan_profiles)")
    return {r["name"] for r in rows}


async def test_migration_on_a_fresh_database(tmp_path):
    db = Database(str(tmp_path / "fresh.db"))
    await db.connect()
    try:
        await db.run_module_migrations("fanpilot", MIGRATIONS)
        assert {"source_sensors", "sensor_mode"} <= await _columns(db)
        presets = await db.fetchall("SELECT * FROM fan_profiles WHERE is_preset = 1")
        assert presets
        assert all(p["source_sensors"] is None and p["sensor_mode"] == "max" for p in presets)
        applied = await db.fetchall(
            "SELECT version FROM applied_migrations WHERE module = 'fanpilot'"
        )
        assert {r["version"] for r in applied} == {"001_initial", "002_multi_sensor"}
    finally:
        await db.close()


async def test_migration_on_a_database_at_the_first_version(tmp_path):
    first_only = tmp_path / "first"
    first_only.mkdir()
    shutil.copy(MIGRATIONS / "001_initial.sql", first_only / "001_initial.sql")

    db = Database(str(tmp_path / "old.db"))
    await db.connect()
    try:
        await db.run_module_migrations("fanpilot", first_only)
        await db.execute(
            "INSERT INTO fan_profiles (name, curve_points, source_sensor) VALUES (?, ?, ?)",
            ("Mine", json.dumps(CURVE), "CPU 1"),
        )
        await db.commit()

        await db.run_module_migrations("fanpilot", MIGRATIONS)

        row = await db.fetchone("SELECT * FROM fan_profiles WHERE name = 'Mine'")
        assert row["source_sensor"] == "CPU 1"
        assert row["source_sensors"] is None
        assert row["sensor_mode"] == "max"
        assert normalize_profile_sensors(row) == (["CPU 1"], "max")
        applied = await db.fetchall(
            "SELECT version FROM applied_migrations WHERE module = 'fanpilot'"
        )
        assert sorted(r["version"] for r in applied) == ["001_initial", "002_multi_sensor"]
    finally:
        await db.close()


# === Routes ===


def _create(client, **extra):
    body = {"name": "multi", "curve_points": CURVE, **extra}
    res = client.post(PROFILES, json=body)
    assert res.status_code == 200, res.text
    return res.json()["profile_id"]


def _get(client, profile_id):
    res = client.get(f"{PROFILES}/{profile_id}")
    assert res.status_code == 200
    return res.json()["profile"]


def test_create_with_several_sensors(client):
    pid = _create(client, source_sensors=["CPU Temp", "Inlet Temp"], sensor_mode="avg")
    profile = _get(client, pid)
    assert profile["source_sensors"] == ["CPU Temp", "Inlet Temp"]
    assert profile["sensor_mode"] == "avg"
    assert profile["source_sensor"] == "CPU Temp"


def test_create_with_the_old_single_sensor_body(client):
    pid = _create(client, source_sensor="Inlet Temp")
    profile = _get(client, pid)
    assert profile["source_sensors"] == ["Inlet Temp"]
    assert profile["sensor_mode"] == "max"
    assert profile["source_sensor"] == "Inlet Temp"


def test_update_mode_only(client):
    pid = _create(client, source_sensors=["CPU Temp", "Inlet Temp"])
    assert client.put(f"{PROFILES}/{pid}", json={"sensor_mode": "avg"}).json()["success"]
    profile = _get(client, pid)
    assert profile["source_sensors"] == ["CPU Temp", "Inlet Temp"]
    assert profile["sensor_mode"] == "avg"


def test_update_list_is_trimmed_and_sets_the_first_sensor(client):
    pid = _create(client)
    res = client.put(f"{PROFILES}/{pid}", json={"source_sensors": [" Exhaust Temp ", "CPU Temp"]})
    assert res.json()["success"]
    profile = _get(client, pid)
    assert profile["source_sensors"] == ["Exhaust Temp", "CPU Temp"]
    assert profile["source_sensor"] == "Exhaust Temp"


def test_update_with_the_old_single_sensor_body_resets_to_one_sensor(client):
    pid = _create(client, source_sensors=["CPU Temp", "Inlet Temp"], sensor_mode="avg")
    assert client.put(f"{PROFILES}/{pid}", json={"source_sensor": "Exhaust Temp"}).json()[
        "success"
    ]
    profile = _get(client, pid)
    assert profile["source_sensors"] == ["Exhaust Temp"]
    assert profile["sensor_mode"] == "max"
    assert profile["source_sensor"] == "Exhaust Temp"


def test_a_body_with_both_fields_uses_the_list(client):
    pid = _create(client, source_sensor="Exhaust Temp", source_sensors=["Inlet Temp", "CPU Temp"])
    assert _get(client, pid)["source_sensors"] == ["Inlet Temp", "CPU Temp"]
    client.put(
        f"{PROFILES}/{pid}",
        json={"source_sensor": "Exhaust Temp", "source_sensors": ["CPU Temp"]},
    )
    profile = _get(client, pid)
    assert profile["source_sensors"] == ["CPU Temp"]
    assert profile["source_sensor"] == "CPU Temp"


def test_listing_shows_presets_as_one_sensor(client):
    profiles = client.get(PROFILES).json()["profiles"]
    presets = [p for p in profiles if p["is_preset"]]
    assert presets
    for p in presets:
        assert p["source_sensors"] == ["CPU Temp"]
        assert p["sensor_mode"] == "max"


_INVALID = [
    {"source_sensors": []},
    {"source_sensors": [f"Temp {i}" for i in range(9)]},
    {"source_sensors": ["CPU Temp", "CPU Temp"]},
    {"source_sensors": ["CPU Temp", "  "]},
    {"source_sensors": [1]},
    {"source_sensors": ["x" * 65]},
    {"sensor_mode": "min"},
]


@pytest.mark.parametrize("bad", _INVALID)
def test_create_refuses_invalid_sensors(client, bad):
    before = len(client.get(PROFILES).json()["profiles"])
    res = client.post(PROFILES, json={"name": "bad", "curve_points": CURVE, **bad})
    assert res.status_code == 422
    assert len(client.get(PROFILES).json()["profiles"]) == before


@pytest.mark.parametrize("bad", _INVALID)
def test_update_refuses_invalid_sensors(client, bad):
    pid = _create(client, source_sensors=["CPU Temp", "Inlet Temp"], sensor_mode="avg")
    before = _get(client, pid)
    res = client.put(f"{PROFILES}/{pid}", json=bad)
    assert res.status_code == 422
    assert _get(client, pid) == before


def test_a_row_edited_by_an_older_version_reads_back_as_its_single_sensor(client, tmp_path):
    pid = _create(client, source_sensors=["CPU Temp", "Exhaust Temp"])
    con = sqlite3.connect(tmp_path / "ipmideck.db")
    with con:
        con.execute("UPDATE fan_profiles SET source_sensor = ? WHERE id = ?", ("Inlet Temp", pid))
    con.close()
    profile = _get(client, pid)
    assert profile["source_sensors"] == ["Inlet Temp"]
    assert profile["source_sensor"] == "Inlet Temp"


# === Control loop ===


def _fresh(value, minutes_old=0):
    ts = datetime.utcnow() - timedelta(minutes=minutes_old)
    return {"value": value, "timestamp": ts.isoformat()}


def _multi_row(mode="max"):
    row = _loop_server_row(server_id="srv-multi", vendor="dell")
    row["source_sensor"] = "CPU 1"
    row["source_sensors"] = json.dumps(["CPU 1", "CPU 2"])
    row["sensor_mode"] = mode
    return row


def _tripped(db) -> bool:
    return any("fanpilot_enabled = 0" in sql for sql, _ in db.executed)


async def test_loop_follows_the_hottest_sensor(monkeypatch):
    readings = {"CPU 1": _fresh(40.0), "CPU 2": _fresh(60.0)}
    db, ipmi, ws = await _drive_loop(monkeypatch, [_multi_row("max")], 1, readings=readings)
    assert [c["speed"] for c in ipmi.speed_calls] == [68]
    assert ws.status[-1]["source_temp"] == 60.0


async def test_loop_follows_the_average(monkeypatch):
    readings = {"CPU 1": _fresh(40.0), "CPU 2": _fresh(60.0)}
    db, ipmi, ws = await _drive_loop(monkeypatch, [_multi_row("avg")], 1, readings=readings)
    assert [c["speed"] for c in ipmi.speed_calls] == [52]
    assert ws.status[-1]["source_temp"] == 50.0


async def test_loop_safety_override_uses_the_hottest_in_average_mode(monkeypatch):
    readings = {"CPU 1": _fresh(40.0), "CPU 2": _fresh(90.0)}
    db, ipmi, ws = await _drive_loop(monkeypatch, [_multi_row("avg")], 1, readings=readings)
    assert [c["speed"] for c in ipmi.speed_calls] == [100]
    assert ws.status[-1]["source_temp"] == 65.0


@pytest.mark.parametrize("missing", [None, {"value": None, "timestamp": None}])
async def test_loop_fails_safe_when_one_sensor_is_missing(monkeypatch, missing):
    readings = {"CPU 1": _fresh(40.0), "CPU 2": missing}
    after_first_tick = {}

    def _age_the_gap(tick):
        if tick == 1:
            after_first_tick["tripped"] = _tripped(get_ctx().db)
            fp_tasks._source_last_seen["srv-multi"] -= 10_000

    db, ipmi, ws = await _drive_loop(
        monkeypatch, [_multi_row()], 2, on_tick=_age_the_gap, readings=readings
    )
    assert after_first_tick["tripped"] is False
    assert ws.status == []
    # The only fan writes are the fail-safe's own, never a curve speed.
    assert all(c["speed"] == 100 for c in ipmi.speed_calls)
    assert _tripped(db)
    critical = [a for a in ws.alerts if a["severity"] == "critical"]
    assert len(critical) == 1
    assert "CPU 2" in critical[0]["source"]


async def test_loop_fails_safe_when_one_sensor_is_stale(monkeypatch):
    readings = {"CPU 1": _fresh(40.0), "CPU 2": _fresh(45.0, minutes_old=10)}
    db, ipmi, ws = await _drive_loop(monkeypatch, [_multi_row()], 1, readings=readings)
    assert _tripped(db)
    assert ws.status == []


async def test_loop_fails_safe_when_one_sensor_reads_an_implausible_value(monkeypatch):
    readings = {"CPU 1": _fresh(40.0), "CPU 2": _fresh(0.0)}
    db, ipmi, ws = await _drive_loop(monkeypatch, [_multi_row()], 3, readings=readings)
    assert ws.status == []
    assert _tripped(db)
    critical = [a for a in ws.alerts if a["severity"] == "critical"]
    assert len(critical) == 1
    assert critical[0]["source"] == "CPU 2"
    assert critical[0]["value"] == 0.0


async def test_loop_implausible_value_does_not_trip_before_the_debounce(monkeypatch):
    readings = {"CPU 1": _fresh(40.0), "CPU 2": _fresh(0.0)}
    db, ipmi, ws = await _drive_loop(monkeypatch, [_multi_row()], 2, readings=readings)
    assert ws.status == []
    assert not _tripped(db)
    assert ipmi.speed_calls == []
