"""IPMI service abstraction — local subprocess or demo mock."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger("ipmideck.ipmi")

# === 08-02 (D-09/D-10): data-driven per-vendor fan dispatch (VendorProfile table) ===
#
# The vendor-specific ipmitool `raw` operand sequences live in ONE place: VENDOR_PROFILES +
# the pure builder build_fan_argv(). set_fan_mode/set_fan_speed look the vendor up, build the
# argv list, then run the UNCHANGED Phase-5 classify/scan pipeline (see _run_fan_argv). Every
# byte below is a corroborated value from 08-RESEARCH "Vendor Command Matrix" — never a guess.
#
# Capability + tier (08-RESEARCH matrix; D-05/D-06/D-07/D-08):
#   dell        fan_capable=True,  tier=tested         (real R720 validation; Dell iDRAC raw 0x30 0x30)
#   supermicro  fan_capable=True,  tier=experimental   (X10+ 0x30 0x70 0x66; BOTH zones per D-07)
#   ibm         fan_capable=True,  tier=experimental   (canonical Sebagabones x3550-M4 0x3a 0x07 layout)
#   hpe         fan_capable=False, tier=monitoring_only (D-05: iLO exposes NO IPMI fan control)
#   lenovo      fan_capable=False, tier=monitoring_only (D-06 gate FAIL: no reliable in-band restore)
#   generic     fan_capable=False, tier=monitoring_only (unknown BMC — never attempt raw writes)


@dataclass(frozen=True)
class VendorProfile:
    """Static per-vendor fan-control capability descriptor (08-02, D-09).

    `fan_capable` gates whether ANY raw fan write is attempted; a False vendor makes
    set_fan_mode/set_fan_speed return FanWriteResult(kind="unsupported") without spawning.
    `tier` is the honest support level surfaced in the UI ("tested" | "experimental" |
    "monitoring_only") — matches the docs-site tiers (D-08).
    """

    vendor: str
    fan_capable: bool
    tier: str  # "tested" | "experimental" | "monitoring_only"


VENDOR_PROFILES: dict[str, VendorProfile] = {
    "dell": VendorProfile("dell", True, "tested"),
    "supermicro": VendorProfile("supermicro", True, "experimental"),
    "ibm": VendorProfile("ibm", True, "experimental"),
    "hpe": VendorProfile("hpe", False, "monitoring_only"),
    "lenovo": VendorProfile("lenovo", False, "monitoring_only"),
    "generic": VendorProfile("generic", False, "monitoring_only"),
}


def get_vendor_profile(vendor: str) -> VendorProfile:
    """Return the VendorProfile for `vendor` (case-insensitive); unknown -> generic.

    The API enum (server_routes.py Literal) already blocks unknown strings with a 422, so the
    generic fallback here is purely defensive (e.g. a legacy DB row that skipped migration)."""
    return VENDOR_PROFILES.get((vendor or "").lower(), VENDOR_PROFILES["generic"])


def is_fan_capable(vendor: str) -> bool:
    """True iff the vendor's fan PWM is reachable via a corroborated raw ipmitool sequence."""
    return get_vendor_profile(vendor).fan_capable


def _duty_hex(duty: int) -> str:
    """Clamp a 0-100 duty percent then hex-encode it as ipmitool expects: 0x00-0x64."""
    return f"0x{max(0, min(100, duty)):02x}"


def build_fan_argv(
    vendor: str, op: str, *, manual: bool | None = None, duty: int | None = None
) -> list[list[str]]:
    """Build the ipmitool `raw ...` operand list(s) for a vendor + operation (pure; no I/O).

    Returns 0..N argv operand-lists (each a `["raw", ...]` list):
      * fan_capable=False vendor            -> []  (caller emits kind="unsupported")
      * op="mode", manual=True/False        -> 0..N argv (IBM manual -> [] no-op; IBM restore -> 2 banks)
      * op="speed", duty=0..100             -> 1..N argv (Supermicro -> 2 zones; IBM -> 2 banks)

    Every byte is a corroborated 08-RESEARCH matrix value. Duty is clamped 0..100 then encoded
    0x00-0x64 (`_duty_hex`). This same builder feeds the demo argv echo (D-17, plan 08-04)."""
    profile = get_vendor_profile(vendor)
    if not profile.fan_capable:
        return []
    v = profile.vendor
    if op == "mode":
        if manual is None:
            raise ValueError("build_fan_argv(op='mode') requires manual=bool")
        if v == "dell":
            # 0x30 0x30 0x01 0x00 = manual; 0x01 = restore BMC auto.
            return [["raw", "0x30", "0x30", "0x01", "0x00" if manual else "0x01"]]
        if v == "supermicro":
            # 0x30 0x45 0x01 0x01 = Full (manual); 0x02 = Optimal (auto). Mode is board-global,
            # so a single Optimal write restores BOTH zones to BMC control (D-07).
            return [["raw", "0x30", "0x45", "0x01", "0x01" if manual else "0x02"]]
        if v == "ibm":
            if manual:
                # No standalone manual command — manual is entered by the speed write's
                # trailing 0x00 (see the speed argv below), so mode-manual is a no-op.
                return []
            # Restore BMC auto on BOTH banks (trailing 0x01 = restore). Canonical x3550-M4 layout.
            return [
                ["raw", "0x3a", "0x07", "0x01", "0xff", "0x01"],
                ["raw", "0x3a", "0x07", "0x02", "0xff", "0x01"],
            ]
    elif op == "speed":
        if duty is None:
            raise ValueError("build_fan_argv(op='speed') requires duty=int")
        dh = _duty_hex(duty)
        if v == "dell":
            # 0x30 0x30 0x02 0xff <duty> = set all fans.
            return [["raw", "0x30", "0x30", "0x02", "0xff", dh]]
        if v == "supermicro":
            # Write the SAME duty to BOTH zones each tick: 0x00 (CPU) then 0x01 (peripheral) — D-07.
            return [
                ["raw", "0x30", "0x70", "0x66", "0x01", "0x00", dh],
                ["raw", "0x30", "0x70", "0x66", "0x01", "0x01", dh],
            ]
        if v == "ibm":
            # Both banks, trailing 0x00 = manual (canonical Sebagabones x3550-M4 layout ONLY —
            # never mix source layouts, per 08-RESEARCH IBM caveat).
            return [
                ["raw", "0x3a", "0x07", "0x01", dh, "0x00"],
                ["raw", "0x3a", "0x07", "0x02", dh, "0x00"],
            ]
    raise ValueError(f"build_fan_argv: unknown op {op!r}")


# Legacy name, now DERIVED from the table so any existing reference stays valid
# (= {"dell", "supermicro", "ibm"} — the fan-capable vendors).
_SUPPORTED_FAN_VENDORS = {v for v, p in VENDOR_PROFILES.items() if p.fan_capable}


# === P0-3 (FANPILOT-READBACK): fan-write completion-code classification ===
#
# ipmitool surfaces an IPMI completion code on stderr as a line of the exact form:
#   Unable to send RAW command (channel=0x0 netfn=0x30 lun=0x0 cmd=0x30 rsp=0xNN): <text>
# (`lib/ipmi_raw.c`). The current `_exec` already raises RuntimeError carrying that whole
# stderr line, so we classify off the MACHINE-STABLE `rsp=0x..` token — NOT the process exit
# code, which ipmitool historically returned as 0 even on raw failures (05-RESEARCH Pitfall 2 /
# ipmitool issue #97). The 2-hex code is vendor-stable; the human text may be localized.
_RSP_RE = re.compile(r"rsp=0x([0-9a-fA-F]{2})")
# Hard rejects — no point retrying (privilege/lockout, malformed payload, disabled command).
_HARD_CCODES = {"d4", "d5", "d6", "c7", "c1", "cc", "c9"}
# Transient — BMC busy / unspecified; safe to retry (bounded).
_TRANSIENT_CCODES = {"c0", "ff"}


@dataclass(frozen=True)
class FanWriteResult:
    """Structured outcome of a fan-write (set_fan_mode / set_fan_speed).

    ok=True only on a confirmed-accepted write. On failure, `kind` is one of
    "rejected" (hard completion-code reject — do NOT retry), "transient" (BMC busy /
    session / timeout — retry bounded) or "unsupported" (vendor cannot be controlled
    over IPMI — no retry, no IPMI fail-safe possible). `ccode` is the 2-hex completion
    code when one was present (else None). `detail` is a human message for the command
    log / alert.
    """

    ok: bool
    kind: str  # "ok" | "rejected" | "transient" | "unsupported"
    ccode: str | None  # e.g. "d4", or None for session-layer / timeout / unsupported
    detail: str  # human message for command_log / alert


def classify_ipmi_error(exc: Exception) -> FanWriteResult:
    """Map an ipmitool failure exception to a structured FanWriteResult.

    Decision tree (05-RESEARCH §"P0-3 Completion-Code Classification"):
      1. TimeoutError                         -> transient (no completion code)
      2. message carries `rsp=0x<code>`:
           code in _TRANSIENT_CCODES (c0/ff)  -> transient
           else (hard ccodes OR unknown code) -> rejected (carry the ccode, surface it)
      3. no rsp token (session / network)     -> transient
    """
    if isinstance(exc, TimeoutError):
        return FanWriteResult(False, "transient", None, str(exc))
    msg = str(exc)
    m = _RSP_RE.search(msg)
    if m:
        code = m.group(1).lower()
        if code in _TRANSIENT_CCODES:
            return FanWriteResult(False, "transient", code, msg)
        # _HARD_CCODES OR an unknown code: treat as a hard reject so it surfaces.
        return FanWriteResult(False, "rejected", code, msg)
    # No rsp=0x token: session-establish failure / network layer -> transient.
    return FanWriteResult(False, "transient", None, msg)


def _scan_write_response(text: str) -> FanWriteResult | None:
    """Return a classified FanWriteResult if `text` carries an IPMI completion code
    (rsp=0xNN), else None. ipmitool can exit 0 yet print a raw-command rejection on
    stdout/stderr (05-RESEARCH Pitfall 2 / C1). Scanning the fan-write OUTPUT — not just
    exceptions — closes the exit-0 false-success hole. Fan-write methods only; generic
    commands are untouched."""
    m = _RSP_RE.search(text or "")
    if m is None:
        return None
    # Reuse the single classifier so c0/ff -> transient, hard/unknown -> rejected.
    return classify_ipmi_error(RuntimeError(text))


# === 08-02 (Pitfall 2): multi-write worst-of fold + bounded transient retry ===
#
# A vendor op can issue MORE than one raw write (Supermicro 2 zones, IBM 2 banks). A partial
# failure (one zone/bank rejected or transient) must NEVER fold to a false ok while half the
# board is uncontrolled. We fold the per-write FanWriteResults to the WORST outcome by this
# severity ladder, and retry the WHOLE argv list when the fold is transient (mirror the loop's
# C2 "retry BOTH writes" rule so a transient never masks a still-uncontrolled bank).
_FAN_RESULT_SEVERITY = {"ok": 0, "transient": 1, "unsupported": 2, "rejected": 3}
# Bounded whole-list retries for a TRANSIENT fan write. Total tries incl. the first; a small
# local bound (the loop-level `_apply_fan_write` retry remains the outer safety net).
_ARGV_RETRY_ATTEMPTS = 3


def _worse_fan_result(current: FanWriteResult | None, new: FanWriteResult) -> FanWriteResult:
    """Fold two FanWriteResults to the worst-of (rejected > unsupported > transient > ok).

    A rejected/transient on ANY write outranks an ok, so the overall op is never a false ok
    while a zone/bank is uncontrolled. The worst result's own ccode/detail is preserved."""
    if current is None:
        return new
    if _FAN_RESULT_SEVERITY.get(new.kind, 3) > _FAN_RESULT_SEVERITY.get(current.kind, 3):
        return new
    return current


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
    ) -> FanWriteResult:
        ...

    @abstractmethod
    async def set_fan_speed(
        self, host: str, user: str, password: str, speed_pct: int, vendor: str = "dell"
    ) -> FanWriteResult:
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

    async def _exec_capture(
        self, host: str, user: str, password: str, args: list[str]
    ) -> tuple[str, str]:
        # Full spawn/kill-reap/-E body. Returns (stdout, stderr) on rc==0 so callers that need
        # BOTH streams (the fan-write methods, for the C1 exit-0 completion-code scan) get them;
        # RAISES RuntimeError on rc!=0 exactly as `_exec` always has. `_exec` is now a thin
        # delegator (returns stdout only) so the ~20 existing callers keep their contract.
        # Only the genuine subprocess SPAWN (asyncio.create_subprocess_exec) is `# pragma: no cover`
        # — it needs a real ipmitool binary + reachable BMC. The kill+reap / error-message branches
        # below ARE exercised by tests/unit/test_ipmi_service.py, which monkeypatches
        # create_subprocess_exec to return a fake proc (timeout / cancel / happy / error paths), so
        # the D-16 lifecycle + D-18 message fallback stay covered and ipmi_service.py stays >= 80.
        # Rider S (SEC-IPMI-PWD-ENV): the password NEVER appears on argv (so it can't show up
        # in `ps`). ipmitool `-E` reads it from the IPMITOOL_PASSWORD environment variable, which
        # we inject ONLY into this child's environment (os.environ.copy() preserves PATH /
        # SystemRoot) — never `os.environ[...] = ...`, which would leak the secret process-wide
        # to every other coroutine. NOTE: the password is still in the child's /proc/<pid>/environ
        # (same-UID/root visibility) — an accepted, documented residual vs the `ps` argv leak (C14).
        # Mitigation policy for the residual: do NOT log IPMITOOL_PASSWORD, do NOT export it
        # process-wide (the os.environ.copy() above keeps it scoped to this child). The longer
        # rationale lives in the 05-RESEARCH Rider-S section (local-only / gitignored doc).
        cmd = ["ipmitool", "-I", "lanplus", "-H", host, "-U", user, "-E", *args]
        # Empty-password gotcha (05-RESEARCH Pitfall 3): ipmitool accepts IPMITOOL_PASSWORD=""
        # and silently authenticates with an empty password. If decryption ever yields a falsy
        # value, refuse here — BEFORE spawning — rather than auth with "".
        if not password:
            raise RuntimeError("empty BMC password after decrypt; refusing to auth with -E")
        child_env = os.environ.copy()  # preserve PATH (+ SystemRoot on Windows)
        child_env["IPMITOOL_PASSWORD"] = password  # inject ONLY for this child
        logger.debug("Executing: ipmitool -I lanplus -H %s -U %s ... %s", host, user, " ".join(args))
        async with self._get_host_lock(host):
            proc = await asyncio.create_subprocess_exec(  # pragma: no cover
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=child_env,
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
            return stdout.decode(), stderr.decode()

    async def _exec(self, host: str, user: str, password: str, args: list[str]) -> str:
        # Thin delegator: preserves the historical contract (returns stdout str, raises on rc!=0)
        # so every NON-fan-write caller and the sel/fru/power/sensor `_exec` stubs keep working
        # unchanged. The fan-write methods call `_exec_capture` directly (they need stderr too).
        stdout, _stderr = await self._exec_capture(host, user, password, args)
        return stdout

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

    async def _run_fan_argv(
        self, host: str, user: str, password: str, argv_list: list[list[str]]
    ) -> FanWriteResult:
        """Issue each argv in `argv_list` through the UNCHANGED Phase-5 per-command pipeline,
        fold worst-of, and retry the WHOLE list on a transient (bounded — Pitfall 1/2).

        Single-write vendors (Dell) pass a 1-element list -> behavior identical to Phase 5.
        Multi-write vendors (Supermicro 2 zones, IBM 2 banks) fold every write to the worst
        outcome, so a rejected/transient on ANY write is never a false ok while a bank is
        uncontrolled. The classify/scan/except lines below are byte-identical to Phase 5;
        only their placement (inside the per-argv loop) changed (D-09)."""

        async def _run_once() -> FanWriteResult:
            worst: FanWriteResult | None = None
            for args in argv_list:
                try:
                    out, err = await self._exec_capture(host, user, password, args)
                except Exception as e:  # classify rejected/transient — never a false success.
                    res = classify_ipmi_error(e)
                else:
                    # C1 / 05-RESEARCH Pitfall 2: ipmitool can exit 0 yet print a completion
                    # code -> scan both streams so an exit-0 rejection is never a false ok.
                    res = _scan_write_response(err) or _scan_write_response(out)
                    if res is None:
                        res = FanWriteResult(True, "ok", None, "")
                worst = _worse_fan_result(worst, res)
            return worst or FanWriteResult(True, "ok", None, "")

        result = await _run_once()
        # C2: a transient on any write retries the WHOLE list (both zones/banks), bounded.
        attempts = 1
        while (
            not result.ok
            and result.kind == "transient"
            and attempts < _ARGV_RETRY_ATTEMPTS
        ):
            await asyncio.sleep(0.1 * attempts)
            result = await _run_once()
            attempts += 1
        return result

    async def set_fan_mode(
        self, host: str, user: str, password: str, manual: bool, vendor: str = "dell"
    ) -> FanWriteResult:
        # 08-02 (D-09): data-driven dispatch. Default vendor="dell" keeps existing call sites
        # (which pass NO vendor kwarg) valid (Decision G).
        vendor = (vendor or "dell").lower()
        if not is_fan_capable(vendor):
            # P0-3 / D-05: unsupported vendor can't be controlled over IPMI — no retry, no IPMI
            # fail-safe possible. Structured result (not a raise) so loop/route handle it uniformly.
            return FanWriteResult(
                False,
                "unsupported",
                None,
                f"Fan control not supported for vendor '{vendor}' "
                f"(supported: {sorted(_SUPPORTED_FAN_VENDORS)})",
            )
        argv_list = build_fan_argv(vendor, "mode", manual=manual)
        if not argv_list:
            # IBM manual-mode is a no-op: manual is entered by the speed write's trailing 0x00.
            return FanWriteResult(True, "ok", None, "")
        return await self._run_fan_argv(host, user, password, argv_list)

    async def set_fan_speed(
        self, host: str, user: str, password: str, speed_pct: int, vendor: str = "dell"
    ) -> FanWriteResult:
        # 08-02 (D-09): data-driven dispatch. Default vendor="dell" (Decision G).
        vendor = (vendor or "dell").lower()
        if not is_fan_capable(vendor):
            # P0-3 / D-05: unsupported vendor — alert-only, no IPMI fail-safe possible.
            return FanWriteResult(
                False,
                "unsupported",
                None,
                f"Fan speed not supported for vendor '{vendor}' "
                f"(supported: {sorted(_SUPPORTED_FAN_VENDORS)})",
            )
        argv_list = build_fan_argv(vendor, "speed", duty=speed_pct)
        if not argv_list:
            # Defensive: a fan-capable vendor with no speed argv (none today) is a no-op ok.
            return FanWriteResult(True, "ok", None, "")
        return await self._run_fan_argv(host, user, password, argv_list)

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
