from __future__ import annotations

import json

import pytest

URL = "/api/system/app-config/display.datetime"

VALID = {
    "timeZone": "America/New_York",
    "timeFormat": "24h",
    "seconds": "hide",
    "dateFormat": "iso",
}


def _put(client, value):
    return client.put(URL, json={"value": value}).json()


def _stored(client):
    return client.get(URL).json()["value"]


def test_unset_value_reads_as_none(client):
    body = client.get(URL).json()
    assert body["success"] is True
    assert body["value"] is None


def test_valid_value_is_stored_as_canonical_json(client):
    raw = json.dumps(VALID, indent=2)  # key order and spacing differ from the canonical form
    body = _put(client, raw)
    canonical = json.dumps(VALID, sort_keys=True, separators=(",", ":"))
    assert body == {"success": True, "key": "display.datetime", "value": canonical}
    assert _stored(client) == canonical
    assert json.loads(_stored(client)) == VALID


@pytest.mark.parametrize(
    "zone",
    ["browser", "UTC", "America/Argentina/Buenos_Aires", "Etc/GMT+5", "America/Port-au-Prince"],
)
def test_accepted_time_zones(client, zone):
    body = _put(client, json.dumps({**VALID, "timeZone": zone}))
    assert body["success"] is True
    assert json.loads(_stored(client))["timeZone"] == zone


@pytest.mark.parametrize("value", [True, False, 5, 1.5, None])
def test_non_string_values_are_rejected(client, value):
    assert _put(client, value) == {"success": False, "error": "invalid_value"}
    assert _stored(client) is None


_DROP = object()


def _variant(**changes):
    """VALID with some fields replaced, or removed when given _DROP."""
    data = {**VALID, **changes}
    return json.dumps({k: v for k, v in data.items() if v is not _DROP})


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "",
        json.dumps([VALID]),
        json.dumps("browser"),
        json.dumps(None),
        json.dumps({**VALID, "timeZone": "UTC", "x": 1}) + " " * 600,  # over the size cap
        _variant(timeZone=_DROP),
        _variant(seconds=_DROP),
        json.dumps({**VALID, "extra": "auto"}),
        _variant(timeFormat="24"),
        _variant(timeFormat="language"),
        _variant(seconds=True),
        _variant(seconds=False),
        _variant(seconds="yes"),
        _variant(dateFormat="dmy"),
        _variant(dateFormat=None),
        _variant(timeZone=""),
        _variant(timeZone="a" * 65),
        _variant(timeZone="a b"),
        _variant(timeZone="<script>"),
        _variant(timeZone="Europe/Rome\n"),
        _variant(timeZone=5),
    ],
)
def test_malformed_values_are_rejected_and_nothing_is_stored(client, raw):
    assert _put(client, raw) == {"success": False, "error": "invalid_value"}
    assert _stored(client) is None


def test_rejected_write_keeps_the_previous_value(client):
    first = _put(client, json.dumps(VALID))
    assert first["success"] is True
    assert _put(client, _variant(timeZone="a b"))["success"] is False
    assert _stored(client) == first["value"]


def test_zone_of_exactly_64_characters_is_accepted(client):
    assert _put(client, _variant(timeZone="a" * 64))["success"] is True
