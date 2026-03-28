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

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        logger.info("WebSocket connected (%d total)", len(self._connections))

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
        await self.broadcast({
            "type": "sensor_update",
            "server_id": server_id,
            "timestamp": timestamp,
            "sensors": sensors,
        })

    async def broadcast_power_status(self, server_id: str, status: str) -> None:
        await self.broadcast({
            "type": "power_status",
            "server_id": server_id,
            "status": status,
        })

    async def broadcast_fanpilot_status(
        self, server_id: str, mode: str, profile: str, speed_pct: int, source_temp: float
    ) -> None:
        await self.broadcast({
            "type": "fanpilot_status",
            "server_id": server_id,
            "mode": mode,
            "active_profile": profile,
            "current_speed_pct": speed_pct,
            "source_temp": source_temp,
        })

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
