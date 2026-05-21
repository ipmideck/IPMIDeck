"""Module system — discovery, loading, lifecycle management."""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine

from fastapi import APIRouter

from backend.core.database import Database
from backend.core.events import EventBus

logger = logging.getLogger("ipmilink.modules")

BackgroundTask = Callable[[], Coroutine[Any, Any, None]]


@dataclass
class ModuleManifest:
    id: str
    name: str
    version: str
    description: str
    author: str = "IPMILink"
    category: str = "general"
    icon: str = "box"
    dependencies: list[str] = field(default_factory=list)
    router: APIRouter | None = None
    background_tasks: list[BackgroundTask] = field(default_factory=list)
    event_handlers: dict[str, Callable] = field(default_factory=dict)
    migrations_dir: Path | None = None
    on_startup: Callable | None = None
    on_shutdown: Callable | None = None
    widgets: list[dict] = field(default_factory=list)


class ModuleLoader:
    """Discovers, loads, and manages modules."""

    BUILTIN_MODULES = ["sensors", "fanpilot", "power", "sel", "fru"]

    def __init__(self, db: Database, event_bus: EventBus):
        self.db = db
        self.event_bus = event_bus
        self._modules: dict[str, ModuleManifest] = {}
        self._enabled: dict[str, bool] = {}
        self._running_tasks: dict[str, list[Any]] = {}  # keyed by module_id
        self._fully_started: set[str] = set()  # modules whose migrations+subscriptions+tasks ran this process

    async def discover_and_load(self, enabled_config: dict[str, Any] | None = None) -> None:
        """Discover built-in modules and load enabled ones."""
        enabled_config = enabled_config or {}

        for mod_id in self.BUILTIN_MODULES:
            try:
                module = importlib.import_module(f"backend.modules.{mod_id}.manifest")
                manifest: ModuleManifest = module.module
            except Exception:
                logger.exception("Failed to load module '%s'", mod_id)
                continue

            # Check if enabled (default: True)
            mod_conf = enabled_config.get(mod_id, {})
            is_enabled = mod_conf.enabled if hasattr(mod_conf, "enabled") else True

            self._modules[mod_id] = manifest
            self._enabled[mod_id] = is_enabled

            if not is_enabled:
                logger.info("Module '%s' is disabled", mod_id)
                continue

            # Check dependencies
            for dep in manifest.dependencies:
                if dep not in self._modules or not self._enabled.get(dep, False):
                    logger.warning(
                        "Module '%s' requires '%s' which is not available/enabled", mod_id, dep
                    )
                    self._enabled[mod_id] = False
                    break

            if not self._enabled[mod_id]:
                continue

            # Run migrations
            if manifest.migrations_dir and manifest.migrations_dir.exists():
                await self.db.run_module_migrations(mod_id, manifest.migrations_dir)

            # Register event handlers
            for event_type, handler in manifest.event_handlers.items():
                self.event_bus.subscribe(event_type, handler)

            logger.info("Module loaded: %s v%s", manifest.name, manifest.version)

    def get_enabled_modules(self) -> list[ModuleManifest]:
        return [m for mid, m in self._modules.items() if self._enabled.get(mid, False)]

    def get_all_modules(self) -> list[ModuleManifest]:
        return list(self._modules.values())

    def get_module(self, module_id: str) -> ModuleManifest | None:
        return self._modules.get(module_id)

    def is_enabled(self, module_id: str) -> bool:
        return self._enabled.get(module_id, False)

    async def set_enabled(self, module_id: str, enabled: bool) -> None:
        self._enabled[module_id] = enabled
        await self.db.set_config(f"modules.{module_id}.enabled", str(enabled).lower())

    def mount_routes(self, app: Any, dependencies: list | None = None) -> None:
        """Mount all enabled module routers on the FastAPI app.

        Per FIX-04 / D-09: only ENABLED modules get their routes mounted.
        Disabled modules return 404 for /api/modules/{id}/* (route never registered).

        `dependencies` is forwarded to FastAPI's include_router for auth gating
        (typically [Depends(require_auth)] from main.py lifespan).
        """
        deps = dependencies or []
        for mod in self.get_enabled_modules():
            if mod.router:
                prefix = f"/api/modules/{mod.id}"
                app.include_router(mod.router, prefix=prefix, tags=[mod.name], dependencies=deps)
                logger.info("Mounted routes: %s -> %s", mod.name, prefix)

    async def start_background_tasks(self) -> None:
        """Start all enabled modules' background tasks.

        Records each started module in ``self._fully_started`` so that runtime
        re-enable (``start_module``) knows whether the module's migrations,
        event subscriptions, and routes were set up this process. Because
        ``discover_and_load`` only runs migrations + event subscriptions for
        modules enabled at startup and this method only iterates enabled
        modules, ``self._fully_started`` ends up containing exactly the modules
        whose tables, event handlers, and routes are live this process.
        """
        import asyncio

        for mod in self.get_enabled_modules():
            if mod.on_startup:
                await mod.on_startup()
            for task_fn in mod.background_tasks:
                task = asyncio.create_task(task_fn(), name=f"module_{mod.id}")
                self._running_tasks.setdefault(mod.id, []).append(task)
                logger.info("Started background task for %s", mod.name)
            self._fully_started.add(mod.id)

    async def start_module(self, module_id: str) -> bool:
        """Start one module's tasks. Returns False (restart_required) if the module
        was disabled at process startup (its migrations/subscriptions/routes were
        never set up this process), True if it restarted cleanly in-process."""
        import asyncio

        mod = self._modules.get(module_id)
        if not mod:
            return False
        if module_id not in self._fully_started:
            # Disabled at startup: tables/event-subscriptions/routes were skipped
            # (discover_and_load) and routes mount once before SPA fallback. Do NOT
            # start tasks against a half-initialized module — require a restart.
            logger.info("Module %s was disabled at startup; enable requires a restart", module_id)
            return False
        if self._running_tasks.get(module_id):
            return True  # already running
        if mod.on_startup:
            await mod.on_startup()
        for task_fn in mod.background_tasks:
            task = asyncio.create_task(task_fn(), name=f"module_{mod.id}")
            self._running_tasks.setdefault(mod.id, []).append(task)
        logger.info("Restarted background tasks for module %s", module_id)
        return True

    async def _stop_one(self, module_id: str) -> None:
        """Cancel one module's own tasks (gathering before hooks) and run its
        on_shutdown. No cascade — used by both stop_module and the cascade sweep."""
        import asyncio

        tasks = self._running_tasks.pop(module_id, [])
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        mod = self._modules.get(module_id)
        if mod and mod.on_shutdown:
            try:
                await mod.on_shutdown()
            except Exception:
                logger.exception("Error in shutdown hook for %s", module_id)
        logger.info("Stopped background tasks for module %s", module_id)

    async def stop_module(self, module_id: str) -> list[str]:
        """Stop one module's tasks AND any loaded module that declares it as a
        dependency (single-level dependents sweep — sufficient for the 5 built-ins;
        NOT a full topological engine). Runs on_shutdown for each. Returns the
        list of dependent module_ids that were also stopped.

        This is the fan-safety path: disabling ``sensors`` stops ``fanpilot`` FIRST
        (running fanpilot's on_shutdown auto-mode restore) before/with ``sensors``,
        so fans are never driven from stale ``sensor_readings``."""
        dependents = [
            mid
            for mid, m in self._modules.items()
            if mid != module_id
            and module_id in m.dependencies
            and self._running_tasks.get(mid)
        ]
        for dep_id in dependents:
            await self._stop_one(dep_id)  # e.g. fanpilot before sensors — runs fan-safety on_shutdown
            self._enabled[dep_id] = False  # reflect that the dependent is no longer running
        await self._stop_one(module_id)
        return dependents

    async def stop_background_tasks(self) -> None:
        """Stop all running background tasks and run shutdown hooks."""
        import asyncio

        all_tasks = [t for tasks in self._running_tasks.values() for t in tasks]
        for task in all_tasks:
            task.cancel()
        if all_tasks:
            # Await cancellation before running hooks (avoids racing on_shutdown
            # against still-cancelling tasks).
            await asyncio.gather(*all_tasks, return_exceptions=True)
        self._running_tasks.clear()

        # Run shutdown hooks (critical for FanPilot safety)
        for mod in self.get_enabled_modules():
            if mod.on_shutdown:
                try:
                    await mod.on_shutdown()
                except Exception:
                    logger.exception("Error in shutdown hook for %s", mod.id)

    def get_widgets_registry(self) -> list[dict]:
        """Get all widget definitions from enabled modules."""
        widgets = []
        for mod in self.get_enabled_modules():
            for w in mod.widgets:
                widgets.append({**w, "module_id": mod.id, "module_name": mod.name})
        return widgets
