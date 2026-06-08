"""FanPilot engine tests (TEST-02): interpolation edges, safety override, hysteresis, retention.

interpolate_curve is a pure function; FanPilotController.compute_fan_speed is small-stateful
(it persists _last_temp / _last_speed / _safety_active across calls on ONE instance). Construct
a fresh controller per stateful scenario.

asyncio_mode="auto" does not affect sync tests; these are plain `def test_*`.
"""

from __future__ import annotations

from backend.modules.fanpilot.engine import FanPilotController, interpolate_curve

CURVE = [{"temp": 40, "speed": 20}, {"temp": 80, "speed": 100}]


# === interpolate_curve ===


def test_interpolate_below_min_returns_first_point_speed():
    assert interpolate_curve(CURVE, 30) == 20


def test_interpolate_above_max_returns_last_point_speed():
    assert interpolate_curve(CURVE, 90) == 100


def test_interpolate_midpoint_linear():
    # 60C is the midpoint of 40..80 -> midpoint of 20..100 = 60.
    assert interpolate_curve(CURVE, 60) == 60


def test_interpolate_empty_curve_full_speed_safety():
    # No curve defined -> 100% (full speed) as a safety default.
    assert interpolate_curve([], 50) == 100


# === compute_fan_speed: safety override ===


def test_compute_safety_override_forces_full_speed():
    c = FanPilotController("s1", hysteresis=3.0, safety_threshold=85.0)
    # temp >= threshold -> 100 regardless of curve.
    assert c.compute_fan_speed(CURVE, 90.0) == 100


# === compute_fan_speed: hysteresis hold ===


def test_compute_hysteresis_holds_speed_on_small_drop():
    """A 2C drop (< 3C hysteresis) must not reduce the previously-commanded speed."""
    c = FanPilotController("s2", hysteresis=3.0, safety_threshold=85.0)
    first = c.compute_fan_speed(CURVE, 60.0)
    # 58C would interpolate lower, but the 2C drop is below the 3C hysteresis band,
    # so the speed is held >= the prior commanded speed.
    second = c.compute_fan_speed(CURVE, 58.0)
    assert second >= first


# === compute_fan_speed: safety RETENTION (REVIEWS MED #12) ===

# A curve that, on its own, computes < 100 well below the safety threshold, so that the
# retained-100 (safety) is distinguishable from the curve value.
RETENTION_CURVE = [{"temp": 40, "speed": 30}, {"temp": 90, "speed": 100}]
# interpolate_curve(RETENTION_CURVE, 83) == 90  (< 100) -> distinguishes retained safety from curve.


# FIXED (was REVIEWS MED #12, debug: fanpilot-safety-retention-hysteresis): compute_fan_speed
# now RETAINS the 100% safety speed once tripped, holding through the (threshold-hysteresis,
# threshold) band until temp clears the lower boundary. The previous xfail(strict=True) that
# proved the latent bug has been removed now that the engine retains safety correctly.
def test_compute_safety_retention_holds_100_until_below_hysteresis_band():
    """After safety activates at 90C, a later 83C call (in the 82..85 band) must STILL return 100.

    threshold=85, hysteresis=3 -> clear boundary = threshold - hysteresis = 82.
      step 1 @90C: safety activates -> 100
      step 2 @83C: 83 is NOT below 82, so safety must be RETAINED -> 100 (the curve would give 90)
      step 3 @81C: 81 < 82 -> safety clears -> curve value (< 100)
    """
    c = FanPilotController("s3", hysteresis=3.0, safety_threshold=85.0)
    assert c.compute_fan_speed(RETENTION_CURVE, 90.0) == 100  # safety activates
    # CORRECT behavior: still 100 because 83 is within the (82, 85) retention band.
    assert c.compute_fan_speed(RETENTION_CURVE, 83.0) == 100  # <-- engine currently returns 90 (BUG)


def test_compute_safety_clears_below_hysteresis_band():
    """Independent of the retention bug: once temp drops below threshold - hysteresis, the
    safety override is cleared and the curve value (< 100) is returned."""
    c = FanPilotController("s4", hysteresis=3.0, safety_threshold=85.0)
    assert c.compute_fan_speed(RETENTION_CURVE, 90.0) == 100  # activate safety
    cleared = c.compute_fan_speed(RETENTION_CURVE, 81.0)  # 81 < 82 -> clears
    assert cleared < 100
