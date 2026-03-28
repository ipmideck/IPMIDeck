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
        self._running_tasks: list[Any] = []

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

    def mount_routes(self, app: Any) -> None:
        """Mount all enabled module routers on the FastAPI app."""
        for mod in self.get_enabled_modules():
            if mod.router:
                prefix = f"/api/modules/{mod.id}"
                app.include_router(mod.router, prefix=prefix, tags=[mod.name])
                logger.info("Mounted routes: %s -> %s", mod.name, prefix)

    async def start_background_tasks(self) -> None:
        """Start all enabled modules' background tasks."""
        import asyncio

        for mod in self.get_enabled_modules():
            if mod.on_startup:
                await mod.on_startup()
            for task_fn in mod.background_tasks:
                task = asyncio.create_task(task_fn(), name=f"module_{mod.id}")
                self._running_tasks.append(task)
                logger.info("Started background task for %s", mod.name)

    async def stop_background_tasks(self) -> None:
        """Stop all running background tasks and run shutdown hooks."""
        for task in self._running_tasks:
            task.cancel()
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
