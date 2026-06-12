"""Module DI container.

Decision J (Codex HIGH fix): use a get_ctx() function call — NOT a direct import
binding of a sentinel like `from backend.modules import _ctx` (which would freeze
the None at import time). The lifespan() in main.py calls set_ctx() with a real
ModuleContext after construction; from then on get_ctx() returns the live container.

The ModuleContext has NO `events` field — the EventBus was removed in 04-W6-01
(see backend/core/events.py tombstone).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.config import AppConfig
    from backend.core.database import Database
    from backend.core.ipmi_service import IPMIService
    from backend.core.websocket import WebSocketManager


@dataclass
class ModuleContext:
    """Explicit dependency container injected once by lifespan() at startup.

    Replaces the former mutable module-globals (`db = None`, `ipmi = None`, ...).
    AuthManager is intentionally NOT in here yet — routes that need the at-rest
    encryption key still do `from backend.main import auth` (documented future
    cleanup: add auth to ModuleContext too).
    """

    db: "Database"
    ipmi: "IPMIService"
    ws: "WebSocketManager"
    config: "AppConfig"


# Holder dict so set_ctx and get_ctx see the SAME mutable container across importers.
# A direct `_ctx = ...` module-global rebinding would NOT propagate to code that did
# `from backend.modules import _ctx` at import time (it would keep the old None) —
# Decision J. The holder gives every get_ctx() call a live lookup.
_ctx_holder: dict[str, "ModuleContext | None"] = {"ctx": None}


def set_ctx(ctx: ModuleContext) -> None:
    """Install the live ModuleContext. Called once by lifespan() in main.py."""
    _ctx_holder["ctx"] = ctx


def get_ctx() -> ModuleContext:
    """Return the live ModuleContext.

    Must be called FRESH at function-use time (inside a route handler or loop body),
    never bound at import time — Decision J. Raises if set_ctx() has not run yet
    (i.e. before lifespan startup), surfacing the ordering bug loudly.
    """
    ctx = _ctx_holder["ctx"]
    if ctx is None:
        raise RuntimeError(
            "ModuleContext not initialized — get_ctx() called before lifespan startup"
        )
    return ctx
