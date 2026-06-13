"""Power status polling loop — periodically broadcasts each server's on/off state (260613-69x).

Mirrors sensors/tasks.py. The power on/off state was previously broadcast ONLY inside the power
command handler (power/routes.py), so a freshly-loaded dashboard showed "Sconosciuto" until a
power action and the WS snapshot cache (_last_power) was empty on connect. This loop polls
get_power_status per online server every cycle and broadcasts it — broadcast_power_status stores
the message in _last_power so a fresh WS connect replays the last known power state.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("ipmilink.modules.power")


async def _broadcast_one_server(server: dict, key) -> None:
    """Poll + broadcast one server's power state with isolated error handling.

    Runs as one coroutine per server under asyncio.gather so one bad BMC never blocks or kills
    the loop. broadcast_power_status stores the status in _last_power so a fresh WS connect
    replays it (this fills the currently-empty snapshot cache).
    """
    from backend.core.crypto import decrypt
    from backend.modules import get_ctx

    ctx = get_ctx()  # Fresh lookup — live ctx (Decision J)
    server_id = server["id"]

    try:
        user = decrypt(server["username_enc"], key)
        pwd = decrypt(server["password_enc"], key)
        status = await ctx.ipmi.get_power_status(server["host"], user, pwd)
        await ctx.ws.broadcast_power_status(server_id, status)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning("power status poll failed server_id=%s: %s", server_id, repr(e))


async def power_status_loop():
    """Background poll cycle — broadcasts each online server's power state every interval.

    Reuses ipmi.power_poll_interval (=30, purpose-built) and falls back to poll_interval. No new
    config knob is introduced (CONTEXT 260613-69x).
    """
    from backend.modules import get_ctx

    ctx = get_ctx()  # Fresh lookup — live ctx (Decision J)
    interval = getattr(ctx.config.ipmi, "power_poll_interval", None) or ctx.config.ipmi.poll_interval
    logger.info("Power status loop started (interval=%ss)", interval)
    while True:
        try:
            ctx = get_ctx()  # Look up fresh inside the loop body (Decision J)
            servers = await ctx.db.fetchall(
                "SELECT id, host, username_enc, password_enc FROM servers WHERE is_online = 1"
            )
            if servers:
                from backend.main import auth  # AuthManager not in ctx — kept (Decision J)

                key = auth.get_encryption_key()
                await asyncio.gather(
                    *(_broadcast_one_server(s, key) for s in servers),
                    return_exceptions=True,
                )
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("Power status loop cancelled")
            raise
        except Exception:
            logger.exception("power_status_loop iteration failed")
            await asyncio.sleep(interval)
