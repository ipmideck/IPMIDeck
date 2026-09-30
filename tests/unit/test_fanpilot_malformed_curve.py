"""A fan curve that cannot be read must not stop the fans from being controlled.

Curve points are stored as free-form JSON with no element schema, so a point missing a
key or holding a non-numeric value reaches the interpolator intact. The interpolator is
total: anything unreadable resolves to full speed, which is the safe answer and matches
the existing empty-curve behaviour.
"""

from __future__ import annotations

import pytest

from backend.modules.fanpilot.engine import FanPilotController, interpolate_curve

MALFORMED_CURVES = [
    pytest.param([{"speed": 50}], id="point-missing-temp"),
    pytest.param([{"temp": 30}], id="point-missing-speed"),
    pytest.param([{"temp": "hot", "speed": 50}], id="non-numeric-temp"),
    pytest.param([{"temp": 30, "speed": None}], id="null-speed"),
    pytest.param({"temp": 30, "speed": 50}, id="mapping-instead-of-list"),
    pytest.param([1, 2, 3], id="bare-numbers"),
    pytest.param(["abc"], id="bare-strings"),
    pytest.param([None], id="null-point"),
]


@pytest.mark.parametrize("curve", MALFORMED_CURVES)
def test_unreadable_curve_resolves_to_full_speed(curve):
    """It must return a usable speed rather than raising."""
    assert interpolate_curve(curve, 55.0) == 100


@pytest.mark.parametrize("curve", MALFORMED_CURVES)
def test_controller_survives_an_unreadable_curve(curve):
    """The per-server controller answers too — this is what the control loop calls."""
    ctrl = FanPilotController("srv-a")
    assert ctrl.compute_fan_speed(curve, 55.0) == 100


def test_valid_curve_is_unaffected():
    """The guard must not change the answer for a well-formed curve."""
    curve = [{"temp": 30, "speed": 20}, {"temp": 70, "speed": 100}]
    assert interpolate_curve(curve, 30.0) == 20
    assert interpolate_curve(curve, 50.0) == 60
    assert interpolate_curve(curve, 70.0) == 100
    assert interpolate_curve(curve, 80.0) == 100


def test_numeric_strings_still_interpolate():
    """Values that arrive as strings from JSON are coerced, not rejected."""
    curve = [{"temp": "30", "speed": "20"}, {"temp": "70", "speed": "100"}]
    assert interpolate_curve(curve, 50.0) == 60


def test_one_broken_server_does_not_starve_the_others():
    """Each server is evaluated independently, so a bad curve is contained.

    The control loop walks its servers in a fixed order, so an exception while
    evaluating one server's curve would abort the pass at the same row on every
    tick and leave every server after it without curve evaluation or fail-safe.
    """
    fleet = [
        ("broken", [{"speed": 50}]),
        ("healthy", [{"temp": 30, "speed": 20}, {"temp": 70, "speed": 100}]),
    ]
    results = {}
    for server_id, curve in fleet:
        ctrl = FanPilotController(server_id)
        results[server_id] = ctrl.compute_fan_speed(curve, 50.0)

    assert results["broken"] == 100, "an unusable curve must resolve to full speed"
    assert results["healthy"] == 60, "the healthy server must still be controlled"
