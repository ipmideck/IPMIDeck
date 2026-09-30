"""Cached update state, the on-demand check, and the unattended daily check.

The network lookups themselves live in :mod:`backend.core.updates`, which is deliberately
synchronous and dependency-free. This module owns everything stateful around them: what was last
seen, when, how often a new attempt is allowed, and whether the unattended check is running.

Two independent switches decide whether anything here reaches the network:

* ``config.updates.enabled`` — the operator's kill switch. With it false the routes that could
  open a socket are never registered and this loop is never started.
* ``updates.check_enabled`` in the database — the operator's answer to the setup question. It
  only governs the *unattended* check. Pressing the button in Settings or the update key in the
  console is an explicit request and is served whenever the kill switch allows it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from backend.core.branding import VERSION
from backend.core.updates import (
    RELEASES_URL,
    UpdateProbe,
    detect_install_method,
    fetch_latest,
    is_newer,
)

logger = logging.getLogger("ipmideck.updates")

CONSENT_KEY = "updates.check_enabled"
_RESULT_KEY = "updates.last_result"

# One day between unattended checks. Deliberately unhurried: a version does not change often
# enough for anything tighter to buy the operator anything, and the anonymous request budget on
# the releases endpoint is shared by every instance behind the same address.
CHECK_INTERVAL_SECONDS = 24 * 60 * 60

# Floor between two network calls on the unattended path. Guards against a restart loop turning
# into a request loop.
MIN_AUTO_INTERVAL_SECONDS = 15 * 60

# Floor between two network calls on the on-demand path. Short enough that a button press feels
# live, long enough that holding the button cannot spend the hourly budget.
MIN_MANUAL_INTERVAL_SECONDS = 60

# After a failure, wait before trying again — doubling from a minute up to six hours. A box with
# no route out should settle into one attempt every few hours, not one every minute.
_BACKOFF_START_SECONDS = 60
_BACKOFF_CEILING_SECONDS = 6 * 60 * 60


@dataclass
class UpdateStatus:
    """Everything the interface needs to describe the update situation in one payload."""

    current_version: str = VERSION
    latest_version: str | None = None
    update_available: bool = False
    is_security: bool = False
    release_url: str = RELEASES_URL
    install_method: str = "unknown"
    checked_at: str | None = None
    error: str | None = None
    from_cache: bool = False

    def as_dict(self) -> dict:
        return {
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "update_available": self.update_available,
            "is_security": self.is_security,
            "release_url": self.release_url,
            "install_method": self.install_method,
            "checked_at": self.checked_at,
            "error": self.error,
            "from_cache": self.from_cache,
        }


def _status_from_probe(probe: UpdateProbe, checked_at: str) -> UpdateStatus:
    return UpdateStatus(
        latest_version=probe.latest_version,
        update_available=is_newer(probe.latest_version, VERSION),
        is_security=probe.is_security,
        release_url=probe.release_url or RELEASES_URL,
        install_method=probe.source,
        checked_at=checked_at,
        error=probe.error,
    )


class UpdateService:
    """Owns the cached result, the rate limits and the unattended check task.

    One instance per running application. The network call is run in a worker thread because the
    standard-library client is blocking and the event loop serves the interface; a version lookup
    must never be able to stall a sensor poll or a WebSocket frame.
    """

    def __init__(self, db, config):
        self._db = db
        self._config = config
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        # Monotonic so a clock change cannot turn a rate limit into a very long wait.
        self._last_attempt: float | None = None
        self._backoff = _BACKOFF_START_SECONDS
        self._consecutive_failures = 0

    # --- consent -------------------------------------------------------------------------

    async def consent_given(self) -> bool:
        raw = await self._db.get_config(CONSENT_KEY, default=None)
        return isinstance(raw, str) and raw.strip().lower() == "true"

    async def set_consent(self, enabled: bool) -> None:
        await self._db.set_config(CONSENT_KEY, "true" if enabled else "false")

    # --- cached state --------------------------------------------------------------------

    async def cached_status(self) -> UpdateStatus:
        """The last known result, with no network access whatsoever.

        A cached payload written by an older version may not carry every field, so it is read
        defensively: a malformed row degrades to "never checked" rather than breaking the page
        that renders it.
        """
        status = UpdateStatus(install_method=detect_install_method())
        raw = await self._db.get_config(_RESULT_KEY, default=None)
        if not raw:
            return status
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            logger.debug("Discarding an unreadable cached update result")
            return status
        if not isinstance(data, dict):
            return status
        status.latest_version = data.get("latest_version")
        status.is_security = bool(data.get("is_security"))
        status.release_url = data.get("release_url") or RELEASES_URL
        status.checked_at = data.get("checked_at")
        status.error = data.get("error")
        # Recomputed rather than trusted: the running version changes on upgrade while the cached
        # row does not, so a stale "update available" would survive the update that resolved it.
        status.update_available = is_newer(status.latest_version, VERSION)
        status.from_cache = True
        return status

    async def _store(self, status: UpdateStatus) -> None:
        await self._db.set_config(
            _RESULT_KEY,
            json.dumps(
                {
                    "latest_version": status.latest_version,
                    "is_security": status.is_security,
                    "release_url": status.release_url,
                    "checked_at": status.checked_at,
                    "error": status.error,
                }
            ),
        )

    # --- checking ------------------------------------------------------------------------

    def _too_soon(self, minimum: float) -> bool:
        return self._last_attempt is not None and (
            time.monotonic() - self._last_attempt
        ) < minimum

    async def check_now(self, minimum_interval: float = MIN_MANUAL_INTERVAL_SECONDS) -> UpdateStatus:
        """Look up the published version, honouring the rate limit.

        Inside the rate-limit window the cached answer is returned with ``from_cache`` set, so a
        caller can tell "nothing changed" from "we did not ask".
        """
        if not self._config.updates.enabled:
            # Reached only if a caller bypasses the route gating; refuse rather than assume.
            status = await self.cached_status()
            status.error = "disabled_by_config"
            return status

        async with self._lock:
            if self._too_soon(minimum_interval):
                return await self.cached_status()

            self._last_attempt = time.monotonic()
            method = detect_install_method()
            probe = await asyncio.to_thread(fetch_latest, method)
            checked_at = datetime.now(timezone.utc).isoformat()
            status = _status_from_probe(probe, checked_at)
            # The channel is what this install actually updates from; a fetcher fallback must not
            # relabel it in the interface.
            status.install_method = method

            if probe.error:
                self._consecutive_failures += 1
                self._backoff = min(self._backoff * 2, _BACKOFF_CEILING_SECONDS)
                logger.info("Update check did not complete (%s)", probe.error)
            else:
                self._consecutive_failures = 0
                self._backoff = _BACKOFF_START_SECONDS
                if status.update_available:
                    logger.info(
                        "A newer version is published: %s (running %s)",
                        status.latest_version,
                        VERSION,
                    )

            await self._store(status)
            return status

    # --- the unattended check ------------------------------------------------------------

    async def _loop(self) -> None:
        while True:
            try:
                status = await self.check_now(minimum_interval=MIN_AUTO_INTERVAL_SECONDS)
                delay = self._backoff if status.error else CHECK_INTERVAL_SECONDS
            except asyncio.CancelledError:
                raise
            except Exception:
                # A version check is never worth taking the process down for.
                logger.exception("The update check task hit an unexpected error")
                delay = self._backoff
            await asyncio.sleep(delay)

    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> bool:
        """Start the unattended check if it is both permitted and wanted. Idempotent."""
        if not self._config.updates.enabled or self.running():
            return False
        if not await self.consent_given():
            return False
        self._task = asyncio.create_task(self._loop())
        logger.info("Update checks enabled — checking now and once a day")
        return True

    async def stop(self) -> None:
        """Stop the unattended check. Safe to call when it was never started."""
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: B014 — shutdown must not raise
            pass

    async def apply_consent(self, enabled: bool) -> None:
        """Persist the answer and make it take effect immediately.

        Without this the operator would have to restart for a Settings toggle to mean anything,
        and "I turned it off" has to be true the moment it is clicked.
        """
        await self.set_consent(enabled)
        if enabled:
            await self.start()
        else:
            await self.stop()
