"""Golden-fixture tests for the IPMI parsers (TEST-01).

These read the hand-authored Dell-flavor raw ipmitool fixtures created in 03-01
(tests/fixtures/ipmi/*.txt) and feed them to the three module-level parsers in
backend.core.ipmi_service. They assert the ACTUAL current structured output.

The sdr/fru assertions are correctness claims (verified against source). The sel
assertions are a REGRESSION LOCK of CURRENT (BUGGY) behavior — see the docstring on
test_sel_field_mapping_locks_current_buggy_behavior below. Parsers are NOT modified here.
"""

from __future__ import annotations

from pathlib import Path

from backend.core.ipmi_service import _parse_fru, _parse_sdr_elist, _parse_sel

FIX = Path(__file__).parent.parent / "fixtures" / "ipmi"


# === sdr ===


def test_sdr_unit_to_type_mapping():
    """UNIT-driven typing is vendor-agnostic: degrees C -> temperature/C, RPM -> fan, etc."""
    sensors = _parse_sdr_elist((FIX / "sdr_elist_dell.txt").read_text())
    by_name = {s["name"]: s for s in sensors}

    assert by_name["Inlet Temp"]["type"] == "temperature"
    assert by_name["Inlet Temp"]["unit"] == "C"
    assert by_name["Inlet Temp"]["value"] == 23.0

    assert by_name["Fan1 RPM"]["type"] == "fan"
    assert by_name["Fan1 RPM"]["unit"] == "RPM"

    assert by_name["Voltage 1"]["type"] == "voltage"
    assert by_name["Voltage 1"]["unit"] == "V"

    assert by_name["Pwr Consumption"]["type"] == "power"
    assert by_name["Pwr Consumption"]["unit"] == "W"

    assert by_name["Current 1"]["type"] == "current"
    assert by_name["Current 1"]["unit"] == "A"

    # "PSU1 Status" reports a hex (0x0180) reading -> discrete (no numeric value)
    assert by_name["PSU1 Status"]["type"] == "discrete"
    assert by_name["PSU1 Status"]["value"] is None

    # "No Reading" line -> status type
    assert by_name["Status"]["type"] == "status"
    assert by_name["Status"]["value"] is None


def test_sdr_processor_temps_named_cpu_by_entity_instance():
    """The two entity-3.1 / 3.2 generic "Temp" rows are renamed "CPU 1" / "CPU 2"."""
    sensors = _parse_sdr_elist((FIX / "sdr_elist_dell.txt").read_text())
    by_name = {s["name"]: s for s in sensors}

    assert "CPU 1" in by_name
    assert "CPU 2" in by_name
    assert by_name["CPU 1"]["entity"] == "3.1"
    assert by_name["CPU 2"]["entity"] == "3.2"
    assert by_name["CPU 1"]["value"] == 42.0
    assert by_name["CPU 2"]["value"] == 44.0
    # No leftover generic "Temp" name survived the processor-entity rename.
    names = [s["name"] for s in sensors]
    assert not any(n == "Temp" or n.startswith("Temp (") for n in names)


# === fru ===


def test_fru_board_product_extracted():
    """A FRU entry with field="Board Product" and value="PowerEdge R720" exists."""
    entries = _parse_fru((FIX / "fru_print_dell.txt").read_text())
    board_product = [e for e in entries if e["field"] == "Board Product"]
    assert len(board_product) == 1
    field = board_product[0]["field"]
    value = board_product[0]["value"]
    assert field == "Board Product"
    assert value == "PowerEdge R720"


def test_fru_empty_value_lines_skipped():
    """Lines whose value is empty after the colon are skipped; only valued fields remain."""
    entries = _parse_fru((FIX / "fru_print_dell.txt").read_text())
    assert all(e["value"] for e in entries)
    # All eight valued fields from the fixture are present.
    fields = {e["field"] for e in entries}
    assert "Board Product" in fields
    assert "Product Name" in fields
    assert "Product Serial" in fields


# === sel ===


def test_sel_three_events_parsed():
    """All three SEL rows are parsed."""
    events = _parse_sel((FIX / "sel_elist_dell.txt").read_text())
    assert len(events) == 3
    assert [e["event_id"] for e in events] == ["1", "2", "3"]


def test_sel_field_mapping_locks_current_buggy_behavior():
    # REGRESSION LOCK (03-RESEARCH Open Question 4 / REVIEWS MED #13): _parse_sel maps parts[2]
    # (the TIME token) to sensor_name — this is a KNOWN-WRONG column mapping. These assertions
    # LOCK CURRENT (BUGGY) BEHAVIOR so a future change is deliberate; they DO NOT assert the
    # parser is correct. Do NOT "fix" the parser without user sign-off; if corrected later,
    # update these assertions intentionally.
    #
    # Raw row: "   1 | 01/15/2026 | 08:30:00 | Temperature #0x0e | Upper Critical going high"
    #          parts[0]="1" parts[1]="01/15/2026" parts[2]="08:30:00" parts[3]="Temperature #0x0e"
    # The TIME token (parts[2]) lands in sensor_name; the real sensor name lands in event_type.
    events = _parse_sel((FIX / "sel_elist_dell.txt").read_text())
    first = events[0]
    assert first["event_id"] == "1"
    assert first["timestamp"] == "01/15/2026"
    # BUG-LOCK: sensor_name is the TIME token, not the actual sensor "Temperature #0x0e".
    assert first["sensor_name"] == "08:30:00"
    assert first["event_type"] == "Temperature #0x0e"
    assert first["description"] == "Upper Critical going high"


def test_sel_failure_row_inferred_critical():
    """The "Failure detected" row is severity "critical" via _infer_severity."""
    events = _parse_sel((FIX / "sel_elist_dell.txt").read_text())
    failure = [e for e in events if "Failure" in e["description"]]
    assert len(failure) == 1
    assert failure[0]["severity"] == "critical"
