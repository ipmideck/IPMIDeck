"""Async event bus for inter-module communication."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

logger = logging.getLogger("ipmilink.events")

EventHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class EventBus:
    """Simple in-process async event bus using asyncio tasks."""

    def __init__(self):
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)
        logger.debug("Subscribed to '%s': %s", event_type, handler.__qualname__)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        if handler in self._handlers[event_type]:
            self._handlers[event_type].remove(handler)

    async def emit(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        handlers = self._handlers.get(event_type, [])
        if not handlers:
            return
        payload = data or {}
        for handler in handlers:
            try:
                asyncio.create_task(handler(payload))
            except Exception:
                logger.exception("Error in event handler for '%s'", event_type)

    def clear(self) -> None:
        self._handlers.clear()
