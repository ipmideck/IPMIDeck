"""FanPilot engine — fan curve interpolation, hysteresis, safety override."""

from __future__ import annotations

import json
import logging

logger = logging.getLogger("ipmilink.modules.fanpilot")


def interpolate_curve(curve_points: list[dict], temperature: float) -> int:
    """Linear interpolation on a fan curve. Returns fan speed percentage (0-100)."""
    if not curve_points:
        return 100  # safety: full speed if no curve

    points = sorted(curve_points, key=lambda p: p["temp"])

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

    def compute_fan_speed(self, curve_points: list[dict], current_temp: float) -> int:
        """Compute the target fan speed with hysteresis and safety override."""
        # Safety override — non-negotiable
        if current_temp >= self.safety_threshold:
            if not self._safety_active:
                logger.warning(
                    "Safety override on %s: temp %.1f°C >= threshold %.1f°C — fans to 100%%",
                    self.server_id, current_temp, self.safety_threshold,
                )
                self._safety_active = True
            self._last_temp = current_temp
            self._last_speed = 100
            return 100

        if self._safety_active and current_temp < self.safety_threshold - self.hysteresis:
            self._safety_active = False
            logger.info("Safety override cleared on %s: temp %.1f°C", self.server_id, current_temp)

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
