"""Tests for the `ipmitool sdr elist` parser — vendor-agnostic typing + duplicate-name dedup.

Fixture is representative ipmitool output from a Dell R720 (synthetic values).
The full dump also contains ~140 discrete/PG/presence sensors with no numeric reading; a
representative discrete line is included to assert those are excluded from numeric output.
"""

from __future__ import annotations

from backend.core.ipmi_service import _parse_sdr_elist

# Real R720 sdr elist value-bearing lines + one discrete (no numeric reading) line.
R720_FIXTURE = """\
Fan1             | 30h | ok  |  7.1 | 3480 RPM
Fan2             | 31h | ok  |  7.1 | 3480 RPM
Fan3             | 32h | ok  |  7.1 | 3360 RPM
Fan4             | 33h | ok  |  7.1 | 3120 RPM
Fan5             | 34h | ok  |  7.1 | 3480 RPM
Fan6             | 35h | ok  |  7.1 | 3480 RPM
Inlet Temp       | 04h | ok  |  7.1 | 21 degrees C
Exhaust Temp     | 01h | ok  |  7.1 | 29 degrees C
Temp             | 0Eh | ok  |  3.1 | 33 degrees C
Temp             | 0Fh | ok  |  3.2 | 34 degrees C
Current 1        | 6Ah | ok  | 10.1 | 0.40 Amps
Current 2        | 6Bh | ok  | 10.2 | 0.40 Amps
Voltage 1        | 6Ch | ok  | 10.1 | 222 Volts
Voltage 2        | 6Dh | ok  | 10.2 | 222 Volts
Pwr Consumption  | 77h | ok  |  7.1 | 182 Watts
Status           | 60h | ok  | 10.1 | 0x01
"""


def _by_type(sensors: list[dict], t: str) -> list[dict]:
    return [s for s in sensors if s["type"] == t]


def test_six_fans_parsed():
    sensors = _parse_sdr_elist(R720_FIXTURE)
    fans = _by_type(sensors, "fan")
    assert len(fans) == 6
    assert all(f["unit"] == "RPM" for f in fans)
    assert {f["name"] for f in fans} == {"Fan1", "Fan2", "Fan3", "Fan4", "Fan5", "Fan6"}
    # RPM values parsed as numbers
    assert {f["value"] for f in fans} == {3480.0, 3360.0, 3120.0}


def test_processor_temps_named_cpu_by_entity_instance():
    """Both CPU temps must survive AND be named "CPU 1" / "CPU 2" from entity 3.1 / 3.2.

    On the R720 both processor temps are reported with the generic name "Temp"; the collision
    bug dropped one. Entity ID 0x03 = Processor (standard), so we name them by entity instance.
    """
    sensors = _parse_sdr_elist(R720_FIXTURE)
    temps = _by_type(sensors, "temperature")
    # Inlet Temp, Exhaust Temp, and TWO CPU temps = 4 total
    assert len(temps) == 4
    values = {t["value"] for t in temps}
    assert 33.0 in values, "CPU 1 temp (33C) lost — duplicate name collision regression"
    assert 34.0 in values, "CPU 2 temp (34C) lost — duplicate name collision regression"
    # Names must be unique so downstream keying (WS / store / history DB) keeps both
    names = [t["name"] for t in temps]
    assert len(names) == len(set(names)), "temperature sensor names must be unique"
    # Processor entity (3.x) temps become "CPU {instance}", not generic "Temp"/"Temp (2)"
    by_name = {t["name"]: t for t in temps}
    assert "CPU 1" in by_name, "entity 3.1 temp should be named 'CPU 1'"
    assert "CPU 2" in by_name, "entity 3.2 temp should be named 'CPU 2'"
    assert by_name["CPU 1"]["value"] == 33.0
    assert by_name["CPU 2"]["value"] == 34.0
    # No leftover generic "Temp" names — processor temps were renamed
    assert not any(n == "Temp" or n.startswith("Temp (") for n in names)


def test_non_processor_duplicate_names_still_dedup_generically():
    """Generic dedup must remain for any NON-processor collision (any vendor)."""
    fixture = """\
Voltage          | 6Ch | ok  | 10.1 | 222 Volts
Voltage          | 6Dh | ok  | 10.2 | 220 Volts
Inlet Temp       | 04h | ok  |  7.1 | 21 degrees C
Inlet Temp       | 05h | ok  |  7.2 | 22 degrees C
"""
    sensors = _parse_sdr_elist(fixture)
    names = [s["name"] for s in sensors]
    # entity 10.x and 7.x are NOT processor -> generic suffix scheme
    assert names.count("Voltage") == 1
    assert "Voltage (2)" in names
    assert names.count("Inlet Temp") == 1
    assert "Inlet Temp (2)" in names


def test_voltage_current_power_present_with_correct_types():
    sensors = _parse_sdr_elist(R720_FIXTURE)

    voltages = _by_type(sensors, "voltage")
    assert {v["name"] for v in voltages} == {"Voltage 1", "Voltage 2"}
    assert all(v["unit"] == "V" and v["value"] == 222.0 for v in voltages)

    currents = _by_type(sensors, "current")
    assert {c["name"] for c in currents} == {"Current 1", "Current 2"}
    assert all(c["unit"] == "A" and c["value"] == 0.40 for c in currents)

    power = _by_type(sensors, "power")
    assert len(power) == 1
    assert power[0]["name"] == "Pwr Consumption"
    assert power[0]["unit"] == "W"
    assert power[0]["value"] == 182.0


def test_discrete_lines_excluded_from_numeric_output():
    """Discrete/status lines (0x.. readings) must not have a numeric value and must not be typed
    as a numeric sensor type, so they never pollute numeric charts/widgets."""
    sensors = _parse_sdr_elist(R720_FIXTURE)
    numeric_types = {"temperature", "fan", "voltage", "power", "current"}
    numeric = [s for s in sensors if s["type"] in numeric_types]
    # All numeric sensors have a real value
    assert all(s["value"] is not None for s in numeric)
    # The 0x01 "Status" line is parsed but NOT numeric
    discrete = [s for s in sensors if s["type"] == "discrete"]
    assert any(s["name"] == "Status" for s in discrete)
    assert all(s["value"] is None for s in discrete)
    # Exactly 15 value-bearing numeric sensors (6 fan + 4 temp + 2 V + 2 A + 1 W)
    assert len(numeric) == 15


def test_extra_disambiguation_fields_preserved():
    """Non-breaking extras: raw id/entity preserved for callers wanting richer disambiguation."""
    sensors = _parse_sdr_elist(R720_FIXTURE)
    temps = sorted(_by_type(sensors, "temperature"), key=lambda s: s["name"])
    cpu_temps = [t for t in temps if t["name"].startswith("CPU ")]
    entities = {t["entity"] for t in cpu_temps}
    # The two CPUs live on different entities (3.1 / 3.2) in the raw dump
    assert entities == {"3.1", "3.2"}
