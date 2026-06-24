"""Power-status polling background task — reads chassis power state and broadcasts via WebSocket.

Cold-start fix (debug: power-controls-widget-unknown-status): before this loop existed,
``broadcast_power_status`` only fired reactively from ``power_command`` AFTER a user action,
so ``WebSocketManager._last_power`` was empty on a fresh page load. The WS snapshot replay
therefore sent no ``power_status`` message, ``usePowerStore`` stayed undefined, and
PowerControlsWidget fell back to "unknown" ("Sconosciuto"). This loop proactively reads the
real chassis power state on an interval and broadcasts it, so the snapshot replay on connect
plus the live broadcasts keep every power widget correct as a single source of truth.

Mirrors ``sensor_polling_loop`` (backend/modules/sensors/tasks.py): per-server concurrent
poll under ``asyncio.gather`` with isolated error handling, a NON-BLOCKING per-server cooldown
so a known-offline BMC is not re-hit every cycle, and a single encryption-key load per cycle.
"""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger("ipmideck.modules.power")

_running = True

# Non-blocking per-server cooldown: server_id -> monotonic ts before which we skip polling.
# A server that times out / errors is placed on this cooldown so we do not re-hit a known-offline
# BMC on every poll cycle. This is a SKIP GATE consulted by power_status_loop — NEVER a sleep,
# so it never blocks polling of the other servers (mirrors PERF-01 in sensor_polling_loop).
_next_retry: dict[str, float] = {}
_COOLDOWN_SECONDS = 60.0  # non-blocking cooldown for a failing server


async def _poll_one_server(server: dict, key) -> None:
    """Poll a single server's chassis power state with isolated error handling.

    Runs as one coroutine per server under ``asyncio.gather`` so one server's timeout or
    error never blocks polling of the others. On failure the server is placed on a
    NON-BLOCKING cooldown (no sleep); on success any cooldown is cleared. Power state is
    intentionally NOT persisted — it is ephemeral live state broadcast over the WebSocket
    (and cached in WebSocketManager._last_power for snapshot replay).
    """
    from backend.core.crypto import decrypt
    from backend.modules import get_ctx

    ctx = get_ctx()  # Fresh lookup — live ctx (Decision J)
    server_id = server["id"]

    try:
        host = server["host"]
        user = decrypt(server["username_enc"], key)
        pwd = decrypt(server["password_enc"], key)

        status = await ctx.ipmi.get_power_status(host, user, pwd)

        # Broadcast (and cache in _last_power for the on-connect snapshot replay). This is
        # the single source of truth consumed by usePowerStore on the frontend.
        await ctx.ws.broadcast_power_status(server_id, status)

        # Success — clear any cooldown so a recovered server resumes polling immediately.
        _next_retry.pop(server_id, None)

    except TimeoutError:
        logger.warning("Power-status poll timeout for server %s", server_id)
        # Non-blocking cooldown — skip this server on subsequent cycles until it expires.
        _next_retry[server_id] = time.monotonic() + _COOLDOWN_SECONDS
    except Exception:
        logger.exception("Error polling power status for server %s", server_id)
        # Non-blocking cooldown — skip this server on subsequent cycles until it expires.
        _next_retry[server_id] = time.monotonic() + _COOLDOWN_SECONDS


async def power_status_loop():
    """Main power-status polling loop — runs until cancelled."""
    from backend.modules import get_ctx

    global _running
    _running = True
    logger.info("Power status polling loop started")

    # Poll-then-sleep ordering (matches sensor_polling_loop): the poll block is at the TOP of
    # the while body and the sleep is at the BOTTOM, so the FIRST poll runs immediately on
    # startup BEFORE any sleep. On a cold boot this broadcasts the real chassis power state
    # within ~1s instead of waiting a full power_poll_interval (~30s) — closing the cold-start
    # "Sconosciuto" window as fast as the BMC can answer.
    while _running:
        try:
            ctx = get_ctx()  # Look up fresh inside the loop body (Decision J)
            servers = await ctx.db.fetchall(
                "SELECT id, host, username_enc, password_enc FROM servers"
            )

            # Non-blocking cooldown filter — skip servers still on cooldown. No sleep.
            now_mono = time.monotonic()
            due = [s for s in servers if _next_retry.get(s["id"], 0.0) <= now_mono]

            # Load the encryption key ONCE per cycle and reuse across all due servers.
            key = None
            if due:
                from backend.main import auth
                key = auth.get_encryption_key()

            # Poll all due servers concurrently — one server's timeout/error never blocks the
            # others. return_exceptions=True so a failing coroutine never cancels the gather
            # (per-server try/except already isolates failures in _poll_one_server).
            await asyncio.gather(
                *(_poll_one_server(s, key) for s in due),
                return_exceptions=True,
            )

        except asyncio.CancelledError:
            logger.info("Power status polling loop cancelled")
            _running = False
            return
        except Exception:
            logger.exception("Error in power status polling loop")

        # Sleep until the next interval. Re-fetch ctx so the interval is valid even if the
        # try block above raised before binding ctx (Decision J — fresh lookup, never stale).
        power_poll_interval = get_ctx().config.ipmi.power_poll_interval
        try:
            await asyncio.sleep(power_poll_interval)
        except asyncio.CancelledError:
            logger.info("Power status polling loop cancelled")
            _running = False
            return
