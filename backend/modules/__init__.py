"""Shared module context — injected by main.py at startup."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.config import AppConfig
    from backend.core.database import Database
    from backend.core.events import EventBus
    from backend.core.ipmi_service import IPMIService
    from backend.core.websocket import WebSocketManager

db: Database = None  # type: ignore
ipmi: IPMIService = None  # type: ignore
events: EventBus = None  # type: ignore
ws: WebSocketManager = None  # type: ignore
config: AppConfig = None  # type: ignore
