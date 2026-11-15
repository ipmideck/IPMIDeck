"""Bounds on what a hostile or malfunctioning BMC can make the app allocate."""

from __future__ import annotations

import backend.core.ipmi_service as svc
from backend.core.ipmi_service import (
    MAX_EVENT_ENTRIES,
    MAX_HOST_LOCKS,
    MAX_INVENTORY_ENTRIES,
    MAX_OUTPUT_BYTES,
    MAX_SENSOR_ENTRIES,
    MAX_SUMMARY_KEYS,
    LocalIPMIService,
    _cap_stream,
    _parse_fru,
    _parse_sdr_elist,
    _parse_sel,
    _parse_sel_info,
)


def test_sensor_parsing_stops_at_the_cap(caplog):
    flood = "\n".join(
        f"Sensor{i} | {i:02X}h | ok | 7.1 | {i} RPM" for i in range(MAX_SENSOR_ENTRIES + 500)
    )
    with caplog.at_level("WARNING"):
        sensors = _parse_sdr_elist(flood)
    assert len(sensors) == MAX_SENSOR_ENTRIES
    # Truncation must never be silent: a dropped sensor could be a fan curve's source.
    assert any("Stopped reading sensors" in r.message for r in caplog.records)


def test_event_log_parsing_stops_at_the_cap():
    flood = "\n".join(
        f"{i} | 01/01/2026 | Sensor | Event | Description" for i in range(MAX_EVENT_ENTRIES + 500)
    )
    assert len(_parse_sel(flood)) == MAX_EVENT_ENTRIES


def test_inventory_parsing_stops_at_the_cap():
    flood = "\n".join(f"Field{i} : value{i}" for i in range(MAX_INVENTORY_ENTRIES + 500))
    assert len(_parse_fru(flood)) == MAX_INVENTORY_ENTRIES


def test_summary_parsing_stops_at_the_cap():
    flood = "\n".join(f"Key{i} : value{i}" for i in range(MAX_SUMMARY_KEYS + 500))
    assert len(_parse_sel_info(flood)) == MAX_SUMMARY_KEYS


def test_real_hardware_output_is_nowhere_near_the_caps():
    """The caps exist for hostile input; a genuine dump must pass through untouched."""
    real = "\n".join(f"Fan{i} | {i:02X}h | ok | 7.1 | {2000 + i} RPM" for i in range(160))
    assert len(_parse_sdr_elist(real)) == 160


def test_oversized_subprocess_output_is_discarded(caplog):
    with caplog.at_level("WARNING"):
        capped = _cap_stream(b"x" * (MAX_OUTPUT_BYTES + 4096), "192.0.2.10", "stdout")
    assert len(capped) == MAX_OUTPUT_BYTES
    assert any("Discarded output past" in r.message for r in caplog.records)


def test_normal_subprocess_output_passes_through_unchanged():
    payload = b"Fan1 | 30h | ok | 7.1 | 2400 RPM\n"
    assert _cap_stream(payload, "192.0.2.10", "stdout") == payload.decode()


def test_undecodable_bytes_do_not_raise():
    """A BMC answering with binary noise must not take down the poll loop."""
    assert _cap_stream(b"\xff\xfe not utf-8", "192.0.2.10", "stdout")


def test_host_locks_stay_bounded():
    """The credential-test endpoint accepts a free-form address, so this is reachable."""
    service = LocalIPMIService()
    for i in range(MAX_HOST_LOCKS + 200):
        service._get_host_lock(f"192.0.2.{i}")
    assert len(service._host_locks) <= MAX_HOST_LOCKS


def test_a_held_lock_is_never_evicted():
    """Dropping a held lock would let two commands reach the same BMC at once."""
    service = LocalIPMIService()
    busy = service._get_host_lock("192.0.2.1")
    # Take the semaphore without awaiting, the way an in-flight command holds it.
    busy._value = 0
    for i in range(MAX_HOST_LOCKS + 200):
        service._get_host_lock(f"198.51.100.{i}")
    assert service._host_locks.get("192.0.2.1") is busy


def test_forgetting_a_host_releases_its_lock():
    service = LocalIPMIService()
    service._get_host_lock("192.0.2.1")
    service.forget_host("192.0.2.1")
    assert "192.0.2.1" not in service._host_locks


def test_forgetting_an_unknown_host_is_harmless():
    LocalIPMIService().forget_host("192.0.2.99")


def test_the_caps_are_documented_as_module_constants():
    """They are meant to be found and raised by an operator with unusual hardware."""
    for name in (
        "MAX_OUTPUT_BYTES", "MAX_SENSOR_ENTRIES", "MAX_EVENT_ENTRIES",
        "MAX_INVENTORY_ENTRIES", "MAX_SUMMARY_KEYS", "MAX_ERROR_MESSAGE_CHARS",
        "MAX_HOST_LOCKS",
    ):
        assert getattr(svc, name) > 0, name
