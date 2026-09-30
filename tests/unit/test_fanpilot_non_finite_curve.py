"""NaN and Infinity in a fan curve resolve to 100% and are refused at the API.

json.loads accepts the bare tokens NaN and Infinity, so a request body can carry them into a
stored curve. int(inf) raises OverflowError and int(nan) raises ValueError outside the
engine's parse guard, which aborted the control pass with no fan write at all.
"""

from __future__ import annotations

import math
import sqlite3

import pytest

from backend.modules.fanpilot.engine import interpolate_curve

PROFILES = "/api/modules/fanpilot/profiles"


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("key", ["temp", "speed"])
def test_non_finite_curve_point_resolves_to_full_speed(bad, key):
    curve = [{"temp": 30, "speed": 20}, {"temp": 80, "speed": 90}]
    curve[1][key] = bad
    for temperature in (10.0, 50.0, 95.0):
        assert interpolate_curve(curve, temperature) == 100


@pytest.mark.parametrize("bad", [math.nan, math.inf])
def test_non_finite_temperature_resolves_to_full_speed(bad):
    assert interpolate_curve([{"temp": 30, "speed": 20}, {"temp": 80, "speed": 90}], bad) == 100


def _raw(client, method, path, body: str):
    return client.request(method, path, content=body, headers={"Content-Type": "application/json"})


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_api_refuses_a_non_finite_curve_point(client, token):
    body = '{"name": "x", "curve_points": [{"temp": 30, "speed": %s}]}' % token
    assert _raw(client, "POST", PROFILES, body).status_code == 422
    listing = client.get(PROFILES)
    assert listing.status_code == 200


@pytest.mark.parametrize(
    "point",
    [
        '{"temp": 30, "speed": 50, "meta": [NaN]}',
        '{"temp": [Infinity], "speed": 50}',
        '{"temp": 30, "speed": 50, "extra": {"deep": [1, -Infinity]}}',
    ],
)
def test_api_refuses_a_non_finite_value_nested_in_a_point(client, point):
    body = '{"name": "x", "curve_points": [%s]}' % point
    assert _raw(client, "POST", PROFILES, body).status_code == 422
    assert client.get(PROFILES).status_code == 200


def test_a_curve_stored_with_nan_before_the_check_does_not_break_the_listing(client, tmp_path):
    created = client.post(
        PROFILES, json={"name": "old", "curve_points": [{"temp": 30, "speed": 50}]}
    ).json()
    profile_id = created["profile_id"]
    con = sqlite3.connect(tmp_path / "ipmideck.db")
    with con:
        con.execute(
            "UPDATE fan_profiles SET curve_points = ? WHERE id = ?",
            ('[{"temp": 30, "speed": NaN}, {"temp": 80, "speed": Infinity}]', profile_id),
        )
    con.close()

    listing = client.get(PROFILES)
    assert listing.status_code == 200
    single = client.get(f"{PROFILES}/{profile_id}")
    assert single.status_code == 200
    assert '"speed":null' in single.text.replace(" ", "")


@pytest.mark.parametrize("field", ["hysteresis", "safety_threshold"])
def test_api_refuses_a_non_finite_threshold(client, field):
    # A NaN safety threshold would make `temp >= threshold` always False and silently
    # disable the safety override.
    body = '{"name": "x", "curve_points": [{"temp": 30, "speed": 50}], "%s": NaN}' % field
    assert _raw(client, "POST", PROFILES, body).status_code == 422


def test_api_refuses_a_non_finite_curve_on_update(client):
    created = client.post(
        PROFILES, json={"name": "ok", "curve_points": [{"temp": 30, "speed": 50}]}
    ).json()
    profile_id = created.get("profile_id")
    assert profile_id is not None
    body = '{"curve_points": [{"temp": NaN, "speed": 50}]}'
    assert _raw(client, "PUT", f"{PROFILES}/{profile_id}", body).status_code == 422


def test_api_still_accepts_a_normal_curve(client):
    r = client.post(
        PROFILES,
        json={"name": "ok", "curve_points": [{"temp": 30, "speed": 20}, {"temp": 80, "speed": 90}]},
    )
    assert r.status_code == 200
    assert r.json().get("success") is not False
