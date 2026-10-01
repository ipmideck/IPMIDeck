"""The update switch in the configuration has to mean "off" however off is written."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from backend.core.config import load_config
from backend.core.updates import UpdateProbe

# Quoted spellings arrive as text. Read as-is, every one of them is a non-empty string and so
# truthy, which is exactly how the switch used to fail open.
OFF_SPELLINGS = [
    "false",
    '"false"',
    "'false'",
    '"False"',
    '"no"',
    '"off"',
    '"0"',
    '""',
    "no",
    "off",
    "0",
]
ON_SPELLINGS = ["true", '"true"', '"yes"', '"on"', '"1"', "yes", "on", "1"]


def _isolate(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("IPMIDECK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IPMIDECK_CONFIG_PATH", str(tmp_path / "config.yaml"))
    monkeypatch.delenv("IPMIDECK_UPDATES_ENABLED", raising=False)


def _write(tmp_path, updates_block: str):
    path = tmp_path / "config.yaml"
    path.write_text(f"updates:\n{updates_block}", encoding="utf-8")
    return path


@pytest.mark.parametrize("written", OFF_SPELLINGS)
def test_every_spelling_of_off_in_the_file_switches_it_off(tmp_path, monkeypatch, written):
    _isolate(tmp_path, monkeypatch)
    path = _write(tmp_path, f"  enabled: {written}\n")
    assert load_config(path).updates.enabled is False, written


@pytest.mark.parametrize("written", ON_SPELLINGS)
def test_every_spelling_of_on_in_the_file_switches_it_on(tmp_path, monkeypatch, written):
    _isolate(tmp_path, monkeypatch)
    path = _write(tmp_path, f"  enabled: {written}\n")
    assert load_config(path).updates.enabled is True, written


@pytest.mark.parametrize("written", ['"disabled"', "null", "", "2", "[false]"])
def test_an_unreadable_value_fails_closed_and_says_so(tmp_path, monkeypatch, caplog, written):
    """A value nobody can interpret is not permission to open a socket."""
    _isolate(tmp_path, monkeypatch)
    path = _write(tmp_path, f"  enabled: {written}\n")
    with caplog.at_level(logging.WARNING, logger="ipmideck.config"):
        assert load_config(path).updates.enabled is False, written
    assert any("updates.enabled" in r.getMessage() for r in caplog.records), written


def test_an_absent_key_keeps_the_default(tmp_path, monkeypatch, caplog):
    _isolate(tmp_path, monkeypatch)
    path = _write(tmp_path, "  unrelated: 1\n")
    with caplog.at_level(logging.WARNING, logger="ipmideck.config"):
        assert load_config(path).updates.enabled is True
    assert not caplog.records


@pytest.mark.parametrize("written, expected", [("false", False), ('"off"', False), ("true", True)])
def test_the_section_written_as_a_single_value_is_read_as_the_switch(
    tmp_path, monkeypatch, written, expected
):
    """"updates: false" is the obvious shortcut; ignoring it would leave the check on."""
    _isolate(tmp_path, monkeypatch)
    path = tmp_path / "config.yaml"
    path.write_text(f"updates: {written}\n", encoding="utf-8")
    assert load_config(path).updates.enabled is expected


def test_an_unreadable_single_value_for_the_section_fails_closed(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    path = tmp_path / "config.yaml"
    path.write_text("updates: disabled\n", encoding="utf-8")
    assert load_config(path).updates.enabled is False


def test_an_empty_section_keeps_the_default(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    path = tmp_path / "config.yaml"
    path.write_text("updates:\n", encoding="utf-8")
    assert load_config(path).updates.enabled is True


def test_no_file_at_all_keeps_the_default(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert load_config(tmp_path / "absent.yaml").updates.enabled is True


@pytest.mark.parametrize("value", ["false", "FALSE", "0", "no", "off", "Off", ""])
def test_the_environment_switches_it_off(tmp_path, monkeypatch, value):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("IPMIDECK_UPDATES_ENABLED", value)
    assert load_config().updates.enabled is False, value


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on", " on "])
def test_the_environment_switches_it_on(tmp_path, monkeypatch, value):
    _isolate(tmp_path, monkeypatch)
    _write(tmp_path, "  enabled: false\n")
    monkeypatch.setenv("IPMIDECK_UPDATES_ENABLED", value)
    assert load_config().updates.enabled is True, value


def test_an_unreadable_environment_value_fails_closed_and_says_so(tmp_path, monkeypatch, caplog):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("IPMIDECK_UPDATES_ENABLED", "disabled")
    with caplog.at_level(logging.WARNING, logger="ipmideck.config"):
        assert load_config().updates.enabled is False
    assert any("IPMIDECK_UPDATES_ENABLED" in r.getMessage() for r in caplog.records)


def test_a_quoted_false_removes_the_routes_that_can_open_a_socket(tmp_path, monkeypatch):
    """The point of the switch, end to end: with the route gone the request never matches it.

    Authentication stays on here, so a registered route would answer 401 and an absent one
    answers 405 from the GET-only page fallback. The lookup is replaced as well, so even a
    route that wrongly ran could not reach the network.
    """
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("IPMIDECK_DEMO", "true")
    monkeypatch.setenv("IPMIDECK_DATA_DB_PATH", str(tmp_path / "ipmideck.db"))
    lookups = []
    monkeypatch.setattr(
        "backend.core.update_service.fetch_latest",
        lambda method: lookups.append(method) or UpdateProbe(source=method, error="stubbed"),
    )
    _write(tmp_path, '  enabled: "false"\n')
    import backend.main as bm

    with TestClient(bm.app) as client:
        assert bm.config.updates.enabled is False
        consent = client.put("/api/updates/consent", json={"enabled": False})
        assert consent.status_code in (404, 405)
        assert client.post("/api/updates/check").status_code in (404, 405)
    assert lookups == []
