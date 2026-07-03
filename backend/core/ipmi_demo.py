"""Demo IPMI service — generates realistic fake sensor data for development."""

from __future__ import annotations

import math
import random
import time

from backend.core.ipmi_service import (
    FanWriteResult,
    IPMIService,
    build_fan_argv,
    is_fan_capable,
)


def _argv_display(argvs: list[list[str]]) -> str:
    """Flatten build_fan_argv() operand-lists to a single display string for the command-log echo.

    e.g. [["raw","0x30","0x70","0x66","0x01","0x00","0x32"], [...0x01...]] ->
    "raw 0x30 0x70 0x66 0x01 0x00 0x32; raw 0x30 0x70 0x66 0x01 0x01 0x32". Empty list -> "".
    """
    return "; ".join(" ".join(a) for a in argvs)


class DemoIPMIService(IPMIService):
    """Mock IPMI service with realistic oscillating sensor data."""

    def __init__(self):
        self._power_states: dict[str, str] = {}
        self._fan_manual: dict[str, bool] = {}
        self._fan_speed: dict[str, int] = {}
        self._start_time = time.time()

    def _t(self) -> float:
        return time.time() - self._start_time

    def _noise(self, amplitude: float = 1.0) -> float:
        return (random.random() - 0.5) * 2 * amplitude

    async def get_sensor_readings(self, host: str, user: str, password: str) -> list[dict]:
        t = self._t()
        base_cpu = 42 + 8 * math.sin(t / 120) + self._noise(2)
        base_inlet = 23 + 2 * math.sin(t / 300) + self._noise(0.5)
        base_exhaust = base_inlet + 8 + self._noise(1)

        fan_speed = self._fan_speed.get(host, 35)
        base_rpm = int(fan_speed * 100 + self._noise(50))

        return [
            {"name": "CPU Temp", "type": "temperature", "value": round(base_cpu, 1), "unit": "C", "status": "ok"},
            {"name": "Inlet Temp", "type": "temperature", "value": round(base_inlet, 1), "unit": "C", "status": "ok"},
            {"name": "Exhaust Temp", "type": "temperature", "value": round(base_exhaust, 1), "unit": "C", "status": "ok"},
            {"name": "Fan 1", "type": "fan", "value": base_rpm + int(self._noise(30)), "unit": "RPM", "status": "ok"},
            {"name": "Fan 2", "type": "fan", "value": base_rpm + int(self._noise(30)), "unit": "RPM", "status": "ok"},
            {"name": "Fan 3", "type": "fan", "value": base_rpm + int(self._noise(30)), "unit": "RPM", "status": "ok"},
            {"name": "Fan 4", "type": "fan", "value": base_rpm + int(self._noise(30)), "unit": "RPM", "status": "ok"},
            {"name": "12V", "type": "voltage", "value": round(12.1 + self._noise(0.08), 2), "unit": "V", "status": "ok"},
            {"name": "5V", "type": "voltage", "value": round(5.02 + self._noise(0.03), 2), "unit": "V", "status": "ok"},
            {"name": "3.3V", "type": "voltage", "value": round(3.31 + self._noise(0.02), 2), "unit": "V", "status": "ok"},
            {"name": "Vcore", "type": "voltage", "value": round(0.82 + self._noise(0.05), 2), "unit": "V", "status": "ok"},
            {"name": "Power", "type": "power", "value": round(175 + 25 * math.sin(t / 60) + self._noise(5), 0), "unit": "W", "status": "ok"},
            {"name": "PSU1 Status", "type": "status", "value": None, "unit": "", "status": "ok"},
            {"name": "PSU2 Status", "type": "status", "value": None, "unit": "", "status": "ok"},
        ]

    async def get_power_status(self, host: str, user: str, password: str) -> str:
        return self._power_states.get(host, "on")

    async def power_command(self, host: str, user: str, password: str, action: str) -> str:
        if action == "on":
            self._power_states[host] = "on"
        elif action in ("off", "soft"):
            self._power_states[host] = "off"
        elif action == "cycle":
            self._power_states[host] = "on"
        elif action == "reset":
            self._power_states[host] = "on"
        return f"Chassis Power Control: {action}"

    async def set_fan_mode(
        self, host: str, user: str, password: str, manual: bool, vendor: str = "dell"
    ) -> FanWriteResult:
        # 08-04 (D-17): vendor-aware demo. Compute the would-be ipmitool argv via the SHARED
        # builder and surface it in `.detail` so the caller (fanpilot /mode route) records it
        # into command_log — per-vendor routing becomes assertable via GET /api/logs WITHOUT
        # hardware. A monitoring-only vendor returns kind="unsupported" exactly as production.
        vendor = (vendor or "dell").lower()
        if not is_fan_capable(vendor):
            return FanWriteResult(
                False, "unsupported", None,
                f"Fan control not supported for vendor '{vendor}'",
            )
        argvs = build_fan_argv(vendor, "mode", manual=manual)
        # P0-3: return a structured ok result so downstream code (loop/route) reads `.ok`.
        # IBM manual-mode is a no-op ([] argv -> "") — same as production.
        self._fan_manual[host] = manual
        return FanWriteResult(True, "ok", None, _argv_display(argvs))

    async def set_fan_speed(
        self, host: str, user: str, password: str, speed_pct: int, vendor: str = "dell"
    ) -> FanWriteResult:
        # 08-04 (D-17): vendor-aware demo argv echo (see set_fan_mode). Supermicro -> both
        # zones, IBM -> both banks, Dell -> single write; monitoring-only -> unsupported.
        vendor = (vendor or "dell").lower()
        if not is_fan_capable(vendor):
            return FanWriteResult(
                False, "unsupported", None,
                f"Fan speed not supported for vendor '{vendor}'",
            )
        argvs = build_fan_argv(vendor, "speed", duty=speed_pct)
        self._fan_speed[host] = max(0, min(100, speed_pct))
        return FanWriteResult(True, "ok", None, _argv_display(argvs))

    async def get_sel(self, host: str, user: str, password: str) -> list[dict]:
        return [
            {"event_id": "1", "timestamp": "01/15/2026 08:30:00", "sensor_name": "CPU Temp", "event_type": "Upper Critical going high", "description": "Reading 92 > Threshold 85", "severity": "critical"},
            {"event_id": "2", "timestamp": "01/15/2026 08:30:15", "sensor_name": "CPU Temp", "event_type": "Upper Critical going low", "description": "Reading 78 < Threshold 85", "severity": "info"},
            {"event_id": "3", "timestamp": "01/10/2026 14:20:00", "sensor_name": "PSU1 Status", "event_type": "Presence detected", "description": "Power Supply AC lost", "severity": "warning"},
            {"event_id": "4", "timestamp": "01/10/2026 14:20:30", "sensor_name": "PSU1 Status", "event_type": "Presence detected", "description": "Power Supply AC restored", "severity": "info"},
            {"event_id": "5", "timestamp": "01/01/2026 00:00:01", "sensor_name": "System Event", "event_type": "System Boot", "description": "System boot initiated", "severity": "info"},
        ]

    async def get_sel_info(self, host: str, user: str, password: str) -> dict:
        return {
            "entries": "5",
            "free_space": "15296 bytes",
            "last_add_time": "01/15/2026 08:30:15",
        }

    async def clear_sel(self, host: str, user: str, password: str) -> None:
        pass  # no-op in demo

    async def get_fru(self, host: str, user: str, password: str) -> list[dict]:
        return [
            {"section": "Board", "field": "Board Mfg", "value": "Dell Inc."},
            {"section": "Board", "field": "Board Product", "value": "PowerEdge R720"},
            {"section": "Board", "field": "Board Serial", "value": "CN000000DEMO00"},
            {"section": "Board", "field": "Board Part Number", "value": "04N3DF"},
            {"section": "Chassis", "field": "Chassis Type", "value": "Rack Mount"},
            {"section": "Chassis", "field": "Chassis Serial", "value": "DEMO123"},
            {"section": "Product", "field": "Product Manufacturer", "value": "Dell Inc."},
            {"section": "Product", "field": "Product Name", "value": "PowerEdge R720"},
            {"section": "Product", "field": "Product Serial", "value": "DEMO123"},
            {"section": "Product", "field": "Product Asset Tag", "value": "R720-DEMO"},
        ]

    async def raw_command(self, host: str, user: str, password: str, args: list[str]) -> str:
        return "Demo mode: raw command simulated"
