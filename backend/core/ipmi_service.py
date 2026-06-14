"""IPMI service abstraction — local subprocess or demo mock."""

from __future__ import annotations

import asyncio
import logging
import re
from abc import ABC, abstractmethod

logger = logging.getLogger("ipmilink.ipmi")

# 04-W4-02: vendors whose fan PWM is reachable via raw ipmitool. Dell is the working
# baseline (R720); Supermicro is documented. HPE iLO actively locks fan control against
# raw commands (no supported byte sequence exists) and "generic" is unknown — both raise
# NotImplementedError so the UI can surface an honest "unsupported" message.
_SUPPORTED_FAN_VENDORS = {"dell", "supermicro"}


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
    async def set_fan_mode(
        self, host: str, user: str, password: str, manual: bool, vendor: str = "dell"
    ) -> None:
        ...

    @abstractmethod
    async def set_fan_speed(
        self, host: str, user: str, password: str, speed_pct: int, vendor: str = "dell"
    ) -> None:
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
        # Only the genuine subprocess SPAWN (asyncio.create_subprocess_exec) is `# pragma: no cover`
        # — it needs a real ipmitool binary + reachable BMC. The kill+reap / error-message branches
        # below ARE exercised by tests/unit/test_ipmi_service.py, which monkeypatches
        # create_subprocess_exec to return a fake proc (timeout / cancel / happy / error paths), so
        # the D-16 lifecycle + D-18 message fallback stay covered and ipmi_service.py stays >= 80.
        cmd = ["ipmitool", "-I", "lanplus", "-H", host, "-U", user, "-P", password, *args]
        logger.debug("Executing: ipmitool -I lanplus -H %s -U %s ... %s", host, user, " ".join(args))
        async with self._get_host_lock(host):
            proc = await asyncio.create_subprocess_exec(  # pragma: no cover
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
            except asyncio.TimeoutError:
                raise TimeoutError(f"ipmitool timed out after {self.timeout}s")
            finally:
                # D-16: ALWAYS terminate + reap — success, timeout, AND CancelledError.
                # There is NO `except CancelledError`, so cancellation propagates after cleanup.
                # REVIEWS HIGH-2: guard BOTH kill() and wait() — the child can exit between the
                # `returncode is None` check and kill(), raising ProcessLookupError from kill().
                if proc.returncode is None:
                    try:
                        proc.kill()
                        await proc.wait()
                    except ProcessLookupError:
                        pass
            if proc.returncode != 0:
                # D-18: stderr OR stdout so code 255 (BMC session exhaustion) is legible.
                msg = stderr.decode().strip() or stdout.decode().strip() or "(no output)"
                raise RuntimeError(f"ipmitool error (code {proc.returncode}): {msg}")
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

    async def set_fan_mode(
        self, host: str, user: str, password: str, manual: bool, vendor: str = "dell"
    ) -> None:
        # 04-W4-02: vendor dispatch. Default vendor="dell" keeps Plan 01's existing
        # call sites (which pass NO vendor kwarg) valid (Decision G).
        vendor = (vendor or "dell").lower()
        if vendor not in _SUPPORTED_FAN_VENDORS:
            raise NotImplementedError(
                f"Fan control not supported for vendor '{vendor}' "
                f"(supported: {sorted(_SUPPORTED_FAN_VENDORS)})"
            )
        if vendor == "dell":
            # 0x30 0x30 0x01 0x00 = manual; 0x01 = auto
            val = "0x00" if manual else "0x01"
            await self._exec(host, user, password, ["raw", "0x30", "0x30", "0x01", val])
        elif vendor == "supermicro":
            # 0x30 0x45 0x01 0x01 = Full (manual); 0x02 = Optimal (auto). Setting the
            # profile to Full is required or Supermicro reverts to thermal-managed
            # mode after ~5 min (RESEARCH Pitfall 5).
            val = "0x01" if manual else "0x02"
            await self._exec(host, user, password, ["raw", "0x30", "0x45", "0x01", val])

    async def set_fan_speed(
        self, host: str, user: str, password: str, speed_pct: int, vendor: str = "dell"
    ) -> None:
        # 04-W4-02: vendor dispatch. Default vendor="dell" (Decision G).
        vendor = (vendor or "dell").lower()
        if vendor not in _SUPPORTED_FAN_VENDORS:
            raise NotImplementedError(
                f"Fan speed not supported for vendor '{vendor}' "
                f"(supported: {sorted(_SUPPORTED_FAN_VENDORS)})"
            )
        speed = max(0, min(100, speed_pct))
        hex_val = f"0x{speed:02x}"
        if vendor == "dell":
            # Dell: 0x30 0x30 0x02 0xff <pct_hex>
            await self._exec(
                host, user, password, ["raw", "0x30", "0x30", "0x02", "0xff", hex_val]
            )
        elif vendor == "supermicro":
            # Supermicro: 0x30 0x70 0x66 0x01 <zone=0x00> <pct_hex>; zone 0 = system fans.
            await self._exec(
                host, user, password, ["raw", "0x30", "0x70", "0x66", "0x01", "0x00", hex_val]
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


# IPMI Entity ID 0x03 = "Processor" (standard, vendor-agnostic — IPMI spec Table 43-13).
# Temperature sensors on a processor entity are CPU temps; we name them "CPU {instance}"
# using the entity instance (3.1 -> CPU 1, 3.2 -> CPU 2). This is more meaningful than the
# generic dedup ("Temp" / "Temp (2)") and is the same regardless of BMC vendor.
_PROCESSOR_ENTITY_ID = "3"


def _parse_sdr_elist(output: str) -> list[dict]:
    """Parse `ipmitool sdr elist` output into structured sensor data.

    Sensor TYPE is derived from the IPMI UNIT (degrees C / RPM / Volts / Watts / Amps),
    which is standardized across vendors even though sensor NAMES are not. The UI is driven
    by `type` + the real name, so no vendor-specific name mapping is needed here.

    Sensor NAMING:
    - Temperature sensors on the PROCESSOR entity (IPMI Entity ID 0x03, standard across all
      vendors) are named "CPU {instance}" from the entity instance (3.1 -> "CPU 1",
      3.2 -> "CPU 2"). On many BMCs (e.g. Dell R720) both CPU temps are reported with the
      generic name "Temp", so this gives them stable, meaningful, distinct names.
    - All OTHER duplicate names are disambiguated GENERICALLY (any vendor): when the same name
      appears more than once in a single dump, the second and later occurrences get a numeric
      suffix — "Voltage", "Voltage (2)", "Voltage (3)" — so every sensor survives as a distinct
      key downstream (WebSocket payload, history DB, frontend store).

    The raw id/entity from the dump are preserved as non-breaking extra fields for callers
    that want richer disambiguation.
    """
    sensors = []
    name_counts: dict[str, int] = {}
    for line in output.strip().splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 5:
            continue
        raw_name = parts[0]
        sensor_id = parts[1]
        entity = parts[3]
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

        # Entity-based naming for processor temperature sensors (vendor agnostic).
        # entity is "id.instance" (e.g. "3.1"); processor entity id is 3.
        entity_id, _, entity_instance = entity.partition(".")
        if sensor_type == "temperature" and entity_id == _PROCESSOR_ENTITY_ID and entity_instance:
            name = f"CPU {entity_instance}"
            # Track so any later collision on this derived name still dedups generically.
            name_counts[name] = name_counts.get(name, 0) + 1
            if name_counts[name] > 1:
                name = f"{name} ({name_counts[name]})"
        else:
            # Generic duplicate-name disambiguation — vendor agnostic.
            count = name_counts.get(raw_name, 0) + 1
            name_counts[raw_name] = count
            name = raw_name if count == 1 else f"{raw_name} ({count})"

        sensors.append({
            "name": name,
            "type": sensor_type,
            "value": value,
            "unit": unit,
            "status": "ok" if status == "ok" else ("warning" if "warn" in status else ("critical" if "crit" in status else status)),
            "sensor_id": sensor_id,
            "entity": entity,
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
