"""WebSocket connection manager for broadcasting sensor data to clients."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("ipmilink.websocket")


class WebSocketManager:
    """Manages WebSocket connections and broadcasts messages."""

    def __init__(self):
        self._connections: list[WebSocket] = []
        # Last broadcast message per server for each replayable channel. Sent to
        # new WS clients on connect so a page refresh shows the last known state
        # immediately instead of waiting up to one poll cycle (~30s) for the next
        # sensor/power/fanpilot broadcast. Alerts are intentionally NOT cached —
        # they're one-shot events, replaying would be misleading.
        self._last_sensor: dict[str, dict[str, Any]] = {}
        self._last_power: dict[str, dict[str, Any]] = {}
        self._last_fanpilot: dict[str, dict[str, Any]] = {}

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        logger.info("WebSocket connected (%d total)", len(self._connections))
        await self._send_snapshot(ws)

    async def _send_snapshot(self, ws: WebSocket) -> None:
        """Replay the most recent sensor/power/fanpilot state to one client."""
        cached: list[dict[str, Any]] = [
            *self._last_sensor.values(),
            *self._last_power.values(),
            *self._last_fanpilot.values(),
        ]
        if not cached:
            return
        try:
            for msg in cached:
                await ws.send_text(json.dumps(msg))
            logger.debug("Replayed %d cached state messages to new WS", len(cached))
        except Exception:
            logger.exception("Failed to replay snapshot to new WS")

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)
        logger.info("WebSocket disconnected (%d remaining)", len(self._connections))

    async def broadcast(self, message: dict[str, Any]) -> None:
        if not self._connections:
            return
        data = json.dumps(message)
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast_sensor_update(
        self, server_id: str, sensors: dict[str, Any], timestamp: str
    ) -> None:
        msg = {
            "type": "sensor_update",
            "server_id": server_id,
            "timestamp": timestamp,
            "sensors": sensors,
        }
        self._last_sensor[server_id] = msg
        await self.broadcast(msg)

    async def broadcast_power_status(self, server_id: str, status: str) -> None:
        msg = {
            "type": "power_status",
            "server_id": server_id,
            "status": status,
        }
        self._last_power[server_id] = msg
        await self.broadcast(msg)

    async def broadcast_fanpilot_status(
        self, server_id: str, mode: str, profile: str, speed_pct: int, source_temp: float
    ) -> None:
        msg = {
            "type": "fanpilot_status",
            "server_id": server_id,
            "mode": mode,
            "active_profile": profile,
            "current_speed_pct": speed_pct,
            "source_temp": source_temp,
        }
        self._last_fanpilot[server_id] = msg
        await self.broadcast(msg)

    def clear_server(self, server_id: str) -> None:
        """Drop cached state for a server (call when a server is deleted)."""
        self._last_sensor.pop(server_id, None)
        self._last_power.pop(server_id, None)
        self._last_fanpilot.pop(server_id, None)

    async def broadcast_alert(
        self, server_id: str, severity: str, sensor: str, message: str, value: float
    ) -> None:
        await self.broadcast({
            "type": "alert",
            "server_id": server_id,
            "severity": severity,
            "sensor": sensor,
            "message": message,
            "value": value,
        })

    @property
    def connection_count(self) -> int:
        return len(self._connections)
