"""IPMI service abstraction — local subprocess or demo mock."""

from __future__ import annotations

import asyncio
import logging
import re
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger("ipmilink.ipmi")


class IPMIService(ABC):
    """Abstract IPMI interface. Implementations: Local (ipmitool) or Demo (mock)."""

    @abstractmethod
    async def get_sensor_readings(self, host: str, user: str, password: str) -> list[dict]:
        ...

    @abstractmethod
    async def get_power_status(self, host: str, user: str, password: str) -> str:
        ...

    @abstractmethod
    async def power_command(self, host: str, user: str, password: str, action: str) -> str:
        ...

    @abstractmethod
    async def set_fan_mode(self, host: str, user: str, password: str, manual: bool) -> None:
        ...

    @abstractmethod
    async def set_fan_speed(self, host: str, user: str, password: str, speed_pct: int) -> None:
        ...

    @abstractmethod
    async def get_sel(self, host: str, user: str, password: str) -> list[dict]:
        ...

    @abstractmethod
    async def get_sel_info(self, host: str, user: str, password: str) -> dict:
        ...

    @abstractmethod
    async def clear_sel(self, host: str, user: str, password: str) -> None:
        ...

    @abstractmethod
    async def get_fru(self, host: str, user: str, password: str) -> list[dict]:
        ...

    @abstractmethod
    async def raw_command(self, host: str, user: str, password: str, args: list[str]) -> str:
        ...


class LocalIPMIService(IPMIService):
    """Executes ipmitool via subprocess."""

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self._host_locks: dict[str, asyncio.Semaphore] = {}

    def _get_host_lock(self, host: str) -> asyncio.Semaphore:
        """Return a per-host semaphore (max 1 concurrent call per BMC)."""
        if host not in self._host_locks:
            self._host_locks[host] = asyncio.Semaphore(1)
        return self._host_locks[host]

    async def _exec(self, host: str, user: str, password: str, args: list[str]) -> str:
        cmd = ["ipmitool", "-I", "lanplus", "-H", host, "-U", user, "-P", password, *args]
        logger.debug("Executing: ipmitool -I lanplus -H %s -U %s ... %s", host, user, " ".join(args))
        async with self._get_host_lock(host):
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
            except asyncio.TimeoutError:
                proc.kill()
                raise TimeoutError(f"ipmitool timed out after {self.timeout}s")

            if proc.returncode != 0:
                err = stderr.decode().strip()
                raise RuntimeError(f"ipmitool error (code {proc.returncode}): {err}")

            return stdout.decode()

    async def get_sensor_readings(self, host: str, user: str, password: str) -> list[dict]:
        output = await self._exec(host, user, password, ["sdr", "elist"])
        return _parse_sdr_elist(output)

    async def get_power_status(self, host: str, user: str, password: str) -> str:
        output = await self._exec(host, user, password, ["chassis", "power", "status"])
        if "is on" in output.lower():
            return "on"
        elif "is off" in output.lower():
            return "off"
        return "unknown"

    async def power_command(self, host: str, user: str, password: str, action: str) -> str:
        valid = {"on", "off", "soft", "reset", "cycle", "status"}
        if action not in valid:
            raise ValueError(f"Invalid power action: {action}")
        output = await self._exec(host, user, password, ["chassis", "power", action])
        return output.strip()

    async def set_fan_mode(self, host: str, user: str, password: str, manual: bool) -> None:
        val = "0x00" if manual else "0x01"
        await self._exec(host, user, password, ["raw", "0x30", "0x30", "0x01", val])

    async def set_fan_speed(self, host: str, user: str, password: str, speed_pct: int) -> None:
        speed = max(0, min(100, speed_pct))
        hex_val = f"0x{speed:02x}"
        await self._exec(
            host, user, password, ["raw", "0x30", "0x30", "0x02", "0xff", hex_val]
        )

    async def get_sel(self, host: str, user: str, password: str) -> list[dict]:
        output = await self._exec(host, user, password, ["sel", "elist"])
        return _parse_sel(output)

    async def get_sel_info(self, host: str, user: str, password: str) -> dict:
        output = await self._exec(host, user, password, ["sel", "info"])
        return _parse_sel_info(output)

    async def clear_sel(self, host: str, user: str, password: str) -> None:
        await self._exec(host, user, password, ["sel", "clear"])

    async def get_fru(self, host: str, user: str, password: str) -> list[dict]:
        output = await self._exec(host, user, password, ["fru", "print"])
        return _parse_fru(output)

    async def raw_command(self, host: str, user: str, password: str, args: list[str]) -> str:
        return await self._exec(host, user, password, ["raw", *args])


# === Parsers ===


def _parse_sdr_elist(output: str) -> list[dict]:
    """Parse `ipmitool sdr elist` output into structured sensor data."""
    sensors = []
    for line in output.strip().splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 5:
            continue
        name = parts[0]
        status = parts[2].lower()
        value_str = parts[4]

        # Parse numeric value and unit
        value = None
        unit = ""
        sensor_type = "unknown"

        match = re.match(r"([\d.]+)\s*(degrees C|RPM|Volts|Watts|Amps)", value_str)
        if match:
            value = float(match.group(1))
            raw_unit = match.group(2)
            if "degrees" in raw_unit:
                unit = "C"
                sensor_type = "temperature"
            elif "RPM" in raw_unit:
                unit = "RPM"
                sensor_type = "fan"
            elif "Volts" in raw_unit:
                unit = "V"
                sensor_type = "voltage"
            elif "Watts" in raw_unit:
                unit = "W"
                sensor_type = "power"
            elif "Amps" in raw_unit:
                unit = "A"
                sensor_type = "current"
        elif value_str.strip().startswith("0x"):
            sensor_type = "discrete"
        else:
            sensor_type = "status"

        sensors.append({
            "name": name,
            "type": sensor_type,
            "value": value,
            "unit": unit,
            "status": "ok" if status == "ok" else ("warning" if "warn" in status else ("critical" if "crit" in status else status)),
        })
    return sensors


def _parse_sel(output: str) -> list[dict]:
    """Parse `ipmitool sel elist` output."""
    events = []
    for line in output.strip().splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4:
            continue
        event = {
            "event_id": parts[0],
            "timestamp": parts[1].strip() if len(parts) > 1 else "",
            "sensor_name": parts[2].strip() if len(parts) > 2 else "",
            "event_type": parts[3].strip() if len(parts) > 3 else "",
            "description": parts[4].strip() if len(parts) > 4 else "",
            "severity": _infer_severity(parts),
        }
        events.append(event)
    return events


def _infer_severity(parts: list[str]) -> str:
    text = " ".join(parts).lower()
    if any(w in text for w in ("critical", "fail", "fault", "error")):
        return "critical"
    if any(w in text for w in ("warning", "warn", "degraded")):
        return "warning"
    return "info"


def _parse_sel_info(output: str) -> dict:
    info = {}
    for line in output.strip().splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            info[key.strip().lower().replace(" ", "_")] = val.strip()
    return info


def _parse_fru(output: str) -> list[dict]:
    """Parse `ipmitool fru print` output into sections."""
    entries = []
    current_section = ""
    for line in output.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if line.endswith(":") or "FRU Device" in line:
            current_section = line.rstrip(":").strip()
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if val:
                entries.append({
                    "section": current_section,
                    "field": key,
                    "value": val,
                })
    return entries
