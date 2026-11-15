"""FanPilot engine — fan curve interpolation, hysteresis, safety override."""

from __future__ import annotations

import json
import logging
import math

logger = logging.getLogger("ipmideck.modules.fanpilot")


# Reasons curve_problem() reports. Each one makes interpolate_curve() answer 100%.
CURVE_EMPTY = "empty"
CURVE_UNREADABLE = "unreadable"
CURVE_NOT_FINITE = "not_finite"

# A profile follows 1 to MAX_SOURCE_SENSORS temperature sensors, combined by one of
# SENSOR_MODES: "max" (the hottest, the default) or "avg" (their mean).
MAX_SOURCE_SENSORS = 8
SENSOR_MODES = ("max", "avg")
DEFAULT_SOURCE_SENSOR = "CPU Temp"
_MAX_SENSOR_NAME_LEN = 64


def clean_sensor_names(values) -> list[str] | None:
    """Trim a list of sensor names, or None when it is not an acceptable selection.

    Acceptable: a list of 1 to MAX_SOURCE_SENSORS strings that are non-empty and at most
    64 characters once trimmed, with no name repeated. Order is kept.
    """
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_SOURCE_SENSORS:
        return None
    names: list[str] = []
    for value in values:
        if not isinstance(value, str):
            return None
        name = value.strip()
        if not name or len(name) > _MAX_SENSOR_NAME_LEN or name in names:
            return None
        names.append(name)
    return names


def normalize_profile_sensors(row) -> tuple[list[str], str]:
    """The (sensors, mode) a stored profile row means.

    source_sensor is always written as the first name of the list, so an older version
    that only knows that column still reads a real sensor. The stored list therefore only
    counts when it is already clean and still starts with source_sensor; anything else
    (no list yet, unreadable text, or a row an older version edited after a downgrade)
    means the single source_sensor. Works on rows that lack the newer keys entirely.
    """
    legacy = row.get("source_sensor") or DEFAULT_SOURCE_SENSOR
    sensors = [legacy]
    stored = row.get("source_sensors")
    if stored is not None:
        try:
            parsed = json.loads(stored)
        except (ValueError, TypeError):
            parsed = None
        if (
            isinstance(parsed, list)
            and clean_sensor_names(parsed) == parsed
            and parsed[0] == row.get("source_sensor")
        ):
            sensors = parsed
    mode = row.get("sensor_mode")
    return sensors, (mode if mode in SENSOR_MODES else "max")


def combine_temps(values: list[float], mode: str) -> float:
    """Combine one reading per selected sensor: the mean for "avg", the hottest otherwise."""
    if mode == "avg":
        return sum(values) / len(values)
    return max(values)


def _parse_curve(curve_points) -> tuple[list[dict] | None, str | None]:
    """Return (points sorted by temp, None) for a usable curve, or (None, reason)."""
    if not curve_points:
        return None, CURVE_EMPTY
    try:
        points = sorted(
            ({"temp": float(p["temp"]), "speed": float(p["speed"])} for p in curve_points),
            key=lambda p: p["temp"],
        )
    except (KeyError, TypeError, ValueError, IndexError):
        return None, CURVE_UNREADABLE
    if not all(math.isfinite(p["temp"]) and math.isfinite(p["speed"]) for p in points):
        # NaN / Infinity would slip past every comparison in interpolate_curve.
        return None, CURVE_NOT_FINITE
    return points, None


def curve_problem(curve_points) -> str | None:
    """Why this curve cannot be used, or None when it can.

    interpolate_curve() answers 100% for exactly the curves this reports, so the caller
    can tell the operator the reason instead of leaving the fans loud with no explanation.
    """
    return _parse_curve(curve_points)[1]


def interpolate_curve(curve_points: list[dict], temperature: float) -> int:
    """Linear interpolation on a fan curve. Returns fan speed percentage (0-100).

    Total by construction: any curve this function cannot read resolves to 100%. Curve
    points are stored as free-form JSON with no element schema, so a point missing a key,
    carrying a non-numeric value, or not being a mapping at all reaches this function
    intact. Raising here would abort the control loop mid-pass and leave the fans of every
    server evaluated later in the same pass pinned at their last commanded speed while
    temperatures climb. Full speed is loud but safe, and it matches what an empty curve
    already does. curve_problem() names the reason.
    """
    points, problem = _parse_curve(curve_points)
    if problem is not None:
        return 100  # safety: full speed for a curve that cannot be used
    if not math.isfinite(temperature):
        return 100  # safety: no usable reading to place on the curve

    # Below minimum point
    if temperature <= points[0]["temp"]:
        return int(points[0]["speed"])

    # Above maximum point
    if temperature >= points[-1]["temp"]:
        return int(points[-1]["speed"])

    # Find the two surrounding points and interpolate
    for i in range(len(points) - 1):
        t0, s0 = points[i]["temp"], points[i]["speed"]
        t1, s1 = points[i + 1]["temp"], points[i + 1]["speed"]
        if t0 <= temperature <= t1:
            ratio = (temperature - t0) / (t1 - t0) if t1 != t0 else 0
            speed = s0 + ratio * (s1 - s0)
            return int(round(speed))

    return 100  # fallback: full speed


class FanPilotController:
    """Manages fan control for a single server."""

    def __init__(self, server_id: str, hysteresis: float = 3.0, safety_threshold: float = 85.0):
        self.server_id = server_id
        self.hysteresis = hysteresis
        self.safety_threshold = safety_threshold
        self._last_temp: float | None = None
        self._last_speed: int | None = None
        self._safety_active = False

    def compute_fan_speed(
        self, curve_points: list[dict], current_temp: float, safety_temp: float | None = None
    ) -> int:
        """Compute the target fan speed with hysteresis and safety override.

        current_temp drives the curve and the hysteresis. safety_temp, when given, is the
        temperature the safety override watches instead: a caller that combines several
        sensors passes the hottest one, so an average can never hide a sensor that is
        over the threshold.
        """
        st = current_temp if safety_temp is None else safety_temp
        # Safety override — non-negotiable
        if st >= self.safety_threshold:
            if not self._safety_active:
                logger.warning(
                    "Safety override on %s: temp %.1f°C >= threshold %.1f°C — fans to 100%%",
                    self.server_id, st, self.safety_threshold,
                )
                self._safety_active = True
            self._last_temp = current_temp
            self._last_speed = 100
            return 100

        if self._safety_active and st < self.safety_threshold - self.hysteresis:
            self._safety_active = False
            logger.info("Safety override cleared on %s: temp %.1f°C", self.server_id, st)

        # Safety override retention — non-negotiable
        # Once tripped, HOLD 100% all the way down through the hysteresis band until temp
        # clears the lower boundary (safety_threshold - hysteresis); only the clear-check
        # above releases it. Without this, fans drop to the curve value as soon as temp
        # dips below the threshold — one band too early.
        if self._safety_active:
            self._last_temp = current_temp
            self._last_speed = 100
            return 100

        # Normal curve interpolation
        target_speed = interpolate_curve(curve_points, current_temp)

        # Apply hysteresis: only reduce speed if temp dropped enough
        if self._last_temp is not None and self._last_speed is not None:
            if current_temp < self._last_temp:
                # Temperature is falling
                temp_drop = self._last_temp - current_temp
                if temp_drop < self.hysteresis:
                    # Not enough drop — keep current speed
                    target_speed = max(target_speed, self._last_speed)

        self._last_temp = current_temp
        self._last_speed = target_speed
        return target_speed
