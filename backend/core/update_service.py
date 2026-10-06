"""Cached update state, the on-demand check, and the unattended daily check.

The network lookups themselves live in :mod:`backend.core.updates`, which is deliberately
synchronous and dependency-free. This module owns everything stateful around them: what was last
seen, when, how often a new attempt is allowed, and whether the unattended check is running.

Two independent switches decide whether anything here reaches the network:

* ``config.updates.enabled`` — the operator's kill switch. With it false the routes that could
  open a socket are never registered and this loop is never started.
* ``updates.check_enabled`` in the database — the operator's answer to the setup question. It
  only governs the *unattended* check, and is on until answered "no": an instance that never saw
  the question (an upgrade skips setup) checks like one that answered yes. Pressing the button in Settings or the update key in the
  console is an explicit request and is served whenever the kill switch allows it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from backend.core.branding import VERSION
from backend.core.updates import (
    RELEASES_URL,
    UpdateProbe,
    detect_install_method,
    fetch_latest,
    is_newer,
    safe_release_url,
    upgrade_command,
)

logger = logging.getLogger("ipmideck.updates")

CONSENT_KEY = "updates.check_enabled"
_RESULT_KEY = "updates.last_result"

# One day between unattended checks. Deliberately unhurried: a version does not change often
# enough for anything tighter to buy the operator anything, and the anonymous request budget on
# the releases endpoint is shared by every instance behind the same address.
CHECK_INTERVAL_SECONDS = 24 * 60 * 60

# Floor between two network calls on the unattended path. Guards against a restart loop turning
# into a request loop, so it is measured against the stored time of the last check as well as
# the in-memory one: a fresh process has no memory of the check its predecessor made a minute ago.
MIN_AUTO_INTERVAL_SECONDS = 15 * 60

# Floor between two network calls on the on-demand path. Short enough that a button press feels
# live, long enough that holding the button cannot spend the hourly budget.
MIN_MANUAL_INTERVAL_SECONDS = 60

# After a failure the unattended check retries from 15 minutes, doubling up to six hours. A box
# with no route out should settle into one attempt every few hours, not one every minute. It starts
# at the floor above because any shorter wait would only be turned into a cache read by it.
_BACKOFF_START_SECONDS = MIN_AUTO_INTERVAL_SECONDS
_BACKOFF_CEILING_SECONDS = 6 * 60 * 60

# A newer version was found but its release notes could not be read yet, so nobody can say whether
# it is a security release. That is usually a release whose notes are not published yet; asking
# again on the daily cadence would leave a security badge missing for up to a day after they are.
_SECURITY_RETRY_SECONDS = 60 * 60

# How many of those hourly re-asks one found version gets before the daily cadence resumes. Notes
# still unreadable after six hours are more likely never coming (a release left unpublished, an
# endpoint that keeps refusing us) than late, and asking every hour for ever would spend the shared
# request budget on nothing.
_SECURITY_RETRY_LIMIT = 6


async def _sleep_unless_woken(wake: asyncio.Event, delay: float) -> bool:
    """Sleep up to ``delay`` seconds; True if ``wake`` was set before they ran out."""
    try:
        await asyncio.wait_for(wake.wait(), timeout=max(delay, 0))
    except TimeoutError:
        return False
    return True


@dataclass
class UpdateStatus:
    """Everything the interface needs to describe the update situation in one payload."""

    current_version: str = VERSION
    latest_version: str | None = None
    update_available: bool = False
    is_security: bool = False
    # True when a newer version was found but its release notes could not be read, so whether it
    # is a security release is not known yet. ``is_security`` false then means "unknown", not "no".
    security_unresolved: bool = False
    release_url: str = RELEASES_URL
    install_method: str = "unknown"
    checked_at: str | None = None
    error: str | None = None
    from_cache: bool = False
    # The release notes of ``latest_version``, when the lookup could read them.
    notes: str | None = None

    def as_dict(self) -> dict:
        return {
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "update_available": self.update_available,
            "is_security": self.is_security,
            "security_unresolved": self.security_unresolved,
            "release_url": self.release_url,
            "install_method": self.install_method,
            "checked_at": self.checked_at,
            "error": self.error,
            "from_cache": self.from_cache,
            "notes": self.notes,
        }


def _status_from_probe(probe: UpdateProbe, checked_at: str) -> UpdateStatus:
    return UpdateStatus(
        latest_version=probe.latest_version,
        update_available=is_newer(probe.latest_version, VERSION),
        is_security=probe.is_security,
        security_unresolved=probe.security_unresolved,
        release_url=safe_release_url(probe.release_url),
        install_method=probe.source,
        checked_at=checked_at,
        error=probe.error,
        notes=probe.notes,
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
        # The found version whose release notes could not be read, and how many lookups in a row
        # have found it so. Every lookup counts, the unattended ones and those made on request
        # alike, so the hourly re-asks stop at the limit whoever made them.
        self._unresolved_version: str | None = None
        self._unresolved_lookups = 0
        # Set when a lookup leaves a security question open, so that a check made on request can
        # cut the unattended check's wait short instead of leaving the question for up to a day.
        self._wake = asyncio.Event()
        # Called once per newer version the unattended check learns of, so the console can say
        # so without anyone asking. Set by the entry point; None leaves it to the log alone.
        self.announce: Callable[[UpdateStatus], None] | None = None
        self._announced_version: str | None = None
        # Handed to the unattended check's current lookup. Cancelling the task cannot stop the
        # worker thread the lookup runs in; setting this tells it not to send its next request.
        self._unattended_cancel: threading.Event | None = None

    # --- consent -------------------------------------------------------------------------

    async def consent_given(self) -> bool:
        # On by default: only an explicit "false" turns the unattended check off. An upgraded
        # instance never runs setup, so it never records an answer, and would otherwise never
        # hear about a release unless someone went looking in Settings.
        raw = await self._db.get_config(CONSENT_KEY, default=None)
        return not (isinstance(raw, str) and raw.strip().lower() == "false")

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
        status.security_unresolved = bool(data.get("security_unresolved"))
        status.release_url = safe_release_url(data.get("release_url"))
        status.checked_at = data.get("checked_at")
        status.error = data.get("error")
        notes = data.get("notes")
        status.notes = notes if isinstance(notes, str) else None
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
                    "security_unresolved": status.security_unresolved,
                    "release_url": status.release_url,
                    "checked_at": status.checked_at,
                    "error": status.error,
                    "notes": status.notes,
                }
            ),
        )

    # --- checking ------------------------------------------------------------------------

    def _too_soon(self, minimum: float) -> bool:
        return self._last_attempt is not None and (
            time.monotonic() - self._last_attempt
        ) < minimum

    async def _checked_recently(self, minimum: float) -> bool:
        """True when the stored result is younger than ``minimum`` seconds.

        A timestamp in the future (a clock that was wrong, then corrected) does not count as
        recent, so it cannot suppress checks until that moment arrives.
        """
        checked_at = (await self.cached_status()).checked_at
        if not checked_at:
            return False
        try:
            then = datetime.fromisoformat(checked_at)
        except (TypeError, ValueError):
            return False
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - then).total_seconds()
        return 0 <= age < minimum

    async def check_now(
        self,
        minimum_interval: float = MIN_MANUAL_INTERVAL_SECONDS,
        *,
        cancel: threading.Event | None = None,
    ) -> UpdateStatus:
        """Look up the published version, honouring the rate limit.

        Inside the rate-limit window the cached answer is returned with ``from_cache`` set, so a
        caller can tell "nothing changed" from "we did not ask". When there is no stored answer to
        repeat, the error is ``not_checked`` rather than a blank status that looks like success.

        ``cancel`` reaches the worker thread that makes the requests, which checks it before each
        one. A caller that may abandon the lookup passes its own, so it can stop the thread ahead
        of cancelling the task; otherwise one is made here, and set if this call is cancelled.
        """
        if not self._config.updates.enabled:
            # Reached only if a caller bypasses the route gating; refuse rather than assume.
            status = await self.cached_status()
            status.error = "disabled_by_config"
            return status

        async with self._lock:
            if self._too_soon(minimum_interval) or await self._checked_recently(minimum_interval):
                status = await self.cached_status()
                status.from_cache = True
                if status.checked_at is None:
                    # The attempt holding the rate limit never stored an answer, as when the
                    # database refused the write. The blank default would otherwise read as "you
                    # are up to date" when nobody knows.
                    status.error = "not_checked"
                return status

            previous_attempt, self._last_attempt = self._last_attempt, time.monotonic()
            method = detect_install_method()
            if cancel is None:
                cancel = threading.Event()
            try:
                probe = await asyncio.to_thread(fetch_latest, method, cancel=cancel)
            except asyncio.CancelledError:
                # Abandoned mid-lookup: the answer was withdrawn, the server is stopping, or the
                # caller went away. The worker thread cannot be cancelled, only told not to send
                # its next request. And an attempt that will never store an answer must not hold
                # the rate limit, or turning the check back on would be served a result nobody
                # wrote instead of checking.
                cancel.set()
                self._last_attempt = previous_attempt
                raise
            except Exception:
                # The lookup is written never to raise. If it does anyway, record it as a failed
                # attempt like any other, so it is stored and backed off rather than leaving the
                # rate limit held over an answer that was never written.
                logger.debug("The update lookup raised unexpectedly", exc_info=True)
                probe = UpdateProbe(source=method, error="invalid_response")
            checked_at = datetime.now(timezone.utc).isoformat()
            status = _status_from_probe(probe, checked_at)
            # The channel is what this install actually updates from; a fetcher fallback must not
            # relabel it in the interface.
            status.install_method = method

            if probe.error:
                # A failed lookup says nothing about what is published, so it must not erase an
                # update an earlier one found: keep what was known and record only that this
                # attempt failed, and when.
                previous = await self.cached_status()
                status.latest_version = previous.latest_version
                status.is_security = previous.is_security
                status.security_unresolved = previous.security_unresolved
                status.release_url = previous.release_url
                status.notes = previous.notes
                status.update_available = is_newer(status.latest_version, VERSION)
                self._consecutive_failures += 1
                logger.info("Update check did not complete (%s)", probe.error)
            elif status.update_available:
                logger.info(
                    "A newer version is published: %s (running %s)",
                    status.latest_version,
                    VERSION,
                )

            await self._store(status)
            if not probe.error:
                # Only once the answer is stored. A database that refuses the write fails this
                # check as surely as the network can, and has to back off like it rather than
                # restart every retry from the shortest wait.
                self._consecutive_failures = 0
                self._backoff = _BACKOFF_START_SECONDS
                self._track_security_question(status)
            return status

    def _track_security_question(self, status: UpdateStatus) -> None:
        """Count the lookups that found a newer version without readable release notes."""
        if not (status.update_available and status.security_unresolved):
            # Answered, or nothing newer to ask about: a later open question starts afresh.
            self._unresolved_version = None
            self._unresolved_lookups = 0
            return
        if status.latest_version != self._unresolved_version:
            self._unresolved_version = status.latest_version
            self._unresolved_lookups = 0
        self._unresolved_lookups += 1
        if self._security_retry_due():
            # A check made on request may find this while the unattended check sleeps through a
            # day-long wait; waking it brings the re-ask within the hour.
            self._wake.set()

    def _security_retry_due(self) -> bool:
        # The lookup that found the question open, then one per hourly re-ask: the re-asks stop
        # once the limit of them has been made.
        return 0 < self._unresolved_lookups <= _SECURITY_RETRY_LIMIT

    # --- the unattended check ------------------------------------------------------------

    def _take_backoff(self) -> float:
        """The wait after a failed attempt; each one used doubles the next, up to the ceiling."""
        delay = self._backoff
        self._backoff = min(self._backoff * 2, _BACKOFF_CEILING_SECONDS)
        return delay

    async def _loop(self) -> None:
        while True:
            try:
                # Asked on every pass rather than trusted from start(): this check runs only on
                # the strength of that answer, so a loop that outlives its withdrawal ends here
                # instead of making one more request.
                if not await self.consent_given():
                    return
                # A fresh one per lookup, kept where stop() can reach it.
                cancel = self._unattended_cancel = threading.Event()
                status = await self.check_now(
                    minimum_interval=MIN_AUTO_INTERVAL_SECONDS, cancel=cancel
                )
                self._announce_once(status)
                if status.from_cache:
                    # A previous run checked moments ago: try again once the floor has passed.
                    delay = MIN_AUTO_INTERVAL_SECONDS
                elif status.error:
                    # Before the security retry: a failure keeps the question an earlier lookup
                    # left open, and an endpoint that is down must not be asked every hour.
                    delay = self._take_backoff()
                elif self._security_retry_due():
                    delay = _SECURITY_RETRY_SECONDS
                else:
                    delay = CHECK_INTERVAL_SECONDS
            except asyncio.CancelledError:
                raise
            except Exception:
                # A version check is never worth taking the process down for.
                logger.exception("The update check task hit an unexpected error")
                delay = self._take_backoff()
            await self._pause(delay)

    def _announce_once(self, status: UpdateStatus) -> None:
        """Tell the operator about a newer version the first time it is known, not every day."""
        version = status.latest_version
        if not (status.update_available and version) or version == self._announced_version:
            return
        self._announced_version = version
        command = upgrade_command(status.install_method, version)
        if self.announce is not None:
            try:
                self.announce(status)
            except Exception:
                logger.debug("The update announcement could not be shown", exc_info=True)
            return
        logger.warning(
            "IPMIDeck %s is available (running %s)%s — %s%s",
            version,
            VERSION,
            ", a security release" if status.is_security else "",
            status.release_url,
            f". Upgrade with: {command}" if command else "",
        )

    async def _pause(self, delay: float) -> None:
        """Wait ``delay`` seconds before the next pass.

        A check made on request in the meantime that leaves a security question open brings the
        next pass forward to an hour after it, as if this loop had found the question itself. It
        only ever shortens the wait.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + delay
        # A wake set before now came from this pass's own lookup, or from a check on request made
        # while this pass ran, which turned this pass into a cache read and so a short wait.
        self._wake.clear()
        while await _sleep_unless_woken(self._wake, delay):
            self._wake.clear()
            delay = min(deadline - loop.time(), _SECURITY_RETRY_SECONDS)

    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> bool:
        """Start the unattended check if it is both permitted and wanted. Idempotent."""
        if not self._config.updates.enabled or self.running():
            return False
        if not await self.consent_given():
            return False
        # Asked again after the read above, which yields: two answers arriving together (a double
        # click, two open tabs) would otherwise both get here and start a second loop that stop()
        # has no handle on.
        if self.running():
            return False
        self._task = asyncio.create_task(self._loop())
        logger.info("Update checks enabled — checking now and once a day")
        return True

    async def stop(self) -> None:
        """Stop the unattended check. Safe to call when it was never started."""
        # The lookup in flight is told first, before the task is cancelled: a cancellation reaches
        # the task only on its next turn of the event loop, and the worker thread could open its
        # next connection in between.
        if self._unattended_cancel is not None:
            self._unattended_cancel.set()
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
