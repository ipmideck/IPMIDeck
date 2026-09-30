"""An unusable fan curve holds the fans at 100% AND tells the operator why.

The 100% answer is the safe one, but on its own it leaves loud fans with no explanation.
The loop reports the reason once per (server, profile, reason) — a warning toast and a
command-log entry that stays visible afterwards — and re-arms once the curve is usable.
These drive the real fanpilot_loop through the fakes in test_fanpilot_failsafe.
"""

from __future__ import annotations

import json

import pytest

import backend.modules.fanpilot.tasks as fp_tasks
from backend.modules.fanpilot.engine import (
    CURVE_EMPTY,
    CURVE_NOT_FINITE,
    CURVE_UNREADABLE,
    curve_problem,
)
from tests.unit.test_fanpilot_failsafe import _drive_loop, _loop_server_row

GOOD_CURVE = json.dumps([{"temp": 30, "speed": 20}, {"temp": 80, "speed": 100}])


@pytest.mark.parametrize(
    "curve, reason",
    [
        ([], CURVE_EMPTY),
        ([{"temp": 30}], CURVE_UNREADABLE),
        ([{"temp": "hot", "speed": 50}], CURVE_UNREADABLE),
        (["not a point"], CURVE_UNREADABLE),
        ([{"temp": 30, "speed": float("nan")}], CURVE_NOT_FINITE),
        ([{"temp": float("inf"), "speed": 50}], CURVE_NOT_FINITE),
        ([{"temp": 30, "speed": 20}, {"temp": 80, "speed": 100}], None),
    ],
)
def test_curve_problem_names_the_reason(curve, reason):
    assert curve_problem(curve) == reason


def _curve_log_entries(db):
    return [
        params for sql, params in db.executed
        if "INSERT INTO command_log" in sql and "held_at_100" in params
    ]


@pytest.mark.parametrize(
    "stored, expected_words",
    [
        (json.dumps([{"temp": 30}]), "missing or not a number"),
        ("[]", "has no points"),
        ("{not json", "not valid JSON"),
    ],
)
async def test_an_unusable_curve_is_held_at_full_speed_and_reported_once(
    monkeypatch, stored, expected_words
):
    server = _loop_server_row(server_id="srv-bad", vendor="dell")
    server["curve_points"] = stored
    server["profile_name"] = "Quiet"

    db, ipmi, ws = await _drive_loop(monkeypatch, [server], n_ticks=3)

    assert ipmi.speed_calls, "the loop must still write the fans"
    assert all(call["speed"] == 100 for call in ipmi.speed_calls)
    curve_alerts = [a for a in ws.alerts if "Fan curve" in a["message"]]
    assert len(curve_alerts) == 1, f"one notice across three ticks, got {ws.alerts}"
    alert = curve_alerts[0]
    assert alert["severity"] == "warning"
    assert "'Quiet'" in alert["message"] and expected_words in alert["message"]
    assert "100%" in alert["message"]
    entries = _curve_log_entries(db)
    assert len(entries) == 1, "the reason must also land in the command log, once"
    assert entries[0][-1] == alert["message"]  # shown as the entry's error text


async def test_the_notice_re_arms_after_the_curve_is_fixed(monkeypatch):
    server = _loop_server_row(server_id="srv-bad", vendor="dell")
    server["curve_points"] = json.dumps([{"temp": 30}])

    def _toggle(tick):
        if tick == 1:
            server["curve_points"] = GOOD_CURVE  # fixed: no notice, normal speed
        elif tick == 2:
            server["curve_points"] = json.dumps([{"temp": 30}])  # broken again

    db, ipmi, ws = await _drive_loop(monkeypatch, [server], n_ticks=3, on_tick=_toggle)

    curve_alerts = [a for a in ws.alerts if "Fan curve" in a["message"]]
    assert len(curve_alerts) == 2, f"broken, fixed, broken again -> two notices: {ws.alerts}"
    speeds = [call["speed"] for call in ipmi.speed_calls]
    assert speeds[0] == 100 and speeds[-1] == 100
    assert any(speed < 100 for speed in speeds), "the fixed curve must drive a normal speed"


async def test_a_usable_curve_raises_no_notice(monkeypatch):
    server = _loop_server_row(server_id="srv-ok", vendor="dell")
    db, ipmi, ws = await _drive_loop(monkeypatch, [server], n_ticks=2)

    assert not [a for a in ws.alerts if "Fan curve" in a["message"]]
    assert not _curve_log_entries(db)
    assert fp_tasks._curve_problem_alerted.get("srv-ok") is None
