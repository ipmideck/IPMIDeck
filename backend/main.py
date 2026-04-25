"""IPMILink — main application entry point."""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from backend.core.auth import AuthManager
from backend.core.config import AppConfig, load_config, save_default_config
from backend.core.database import Database
from backend.core.events import EventBus
from backend.core.modules import ModuleLoader
from backend.core.websocket import WebSocketManager

logger = logging.getLogger("ipmilink")

# === Global app state (set during lifespan) ===
config: AppConfig = AppConfig()
db: Database = Database("")
auth: AuthManager = AuthManager(db)
event_bus: EventBus = EventBus()
ws_manager: WebSocketManager = WebSocketManager()
module_loader: ModuleLoader = ModuleLoader(db, event_bus)
ipmi_service = None  # Set during startup based on config.demo


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    global config, db, auth, event_bus, ws_manager, module_loader, ipmi_service

    # Load config
    config = load_config()
    _setup_logging(config.logging.level)

    if config.demo:
        logger.info("*** DEMO MODE — no real hardware ***")

    # Save default config if missing
    data_dir = Path(config.data.db_path).parent
    save_default_config(data_dir / "config.yaml")

    # Connect database
    db = Database(config.data.db_path)
    await db.connect()

    # Initialize auth
    auth = AuthManager(db)
    await auth.initialize()

    # Initialize IPMI service
    if config.demo:
        from backend.core.ipmi_demo import DemoIPMIService
        ipmi_service = DemoIPMIService()
    else:
        from backend.core.ipmi_service import LocalIPMIService
        ipmi_service = LocalIPMIService(timeout=config.ipmi.command_timeout)

    # Inject globals into modules package
    import backend.modules as modules_pkg
    modules_pkg.db = db
    modules_pkg.ipmi = ipmi_service
    modules_pkg.events = event_bus
    modules_pkg.ws = ws_manager
    modules_pkg.config = config

    # Load modules (discover, run migrations, register events)
    # Routes are already mounted statically below — this just does DB + events + tasks
    module_loader = ModuleLoader(db, event_bus)
    await module_loader.discover_and_load(config.modules)

    # Start module background tasks
    await module_loader.start_background_tasks()

    logger.info("IPMILink started on %s:%d", config.server.host, config.server.port)
    if config.demo:
        logger.info("Demo mode active — 2 virtual servers with simulated data")

    yield

    # Shutdown
    logger.info("Shutting down...")
    await module_loader.stop_background_tasks()
    await db.close()
    logger.info("Shutdown complete")


# === FastAPI App ===

app = FastAPI(
    title="IPMILink",
    version="2.0.0-alpha.1",
    lifespan=lifespan,
)


# === WebSocket endpoint ===

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# === Mount API routes (static, at import time) ===

from backend.api.auth_routes import router as auth_router
from backend.api.server_routes import router as server_router
from backend.api.system_routes import router as system_router
from backend.api.dashboard_routes import router as dashboard_router
from backend.api.module_routes import router as module_router

app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])
app.include_router(server_router, prefix="/api/servers", tags=["Servers"])
app.include_router(system_router, prefix="/api", tags=["System"])
app.include_router(dashboard_router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(module_router, prefix="/api/admin/modules", tags=["Modules"])

# === Mount module routes statically (imported at module level) ===

from backend.modules.sensors.routes import router as sensors_router
from backend.modules.fanpilot.routes import router as fanpilot_router
from backend.modules.power.routes import router as power_router
from backend.modules.sel.routes import router as sel_router
from backend.modules.fru.routes import router as fru_router

app.include_router(sensors_router, prefix="/api/modules/sensors", tags=["Sensors"])
app.include_router(fanpilot_router, prefix="/api/modules/fanpilot", tags=["FanPilot"])
app.include_router(power_router, prefix="/api/modules/power", tags=["Power"])
app.include_router(sel_router, prefix="/api/modules/sel", tags=["SEL"])
app.include_router(fru_router, prefix="/api/modules/fru", tags=["FRU"])

# === Serve frontend static files (SPA with fallback to index.html) ===
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    from fastapi.responses import FileResponse

    # Serve static assets (JS, CSS, images) directly
    app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="static-assets")

    # SPA fallback: any non-API route returns index.html for React Router
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Try to serve the exact file first (favicon.svg, etc.)
        file_path = static_dir / full_path
        if full_path and file_path.is_file():
            return FileResponse(file_path)
        # Otherwise return index.html for React Router
        return FileResponse(static_dir / "index.html")


# === CLI entry point ===

def cli():
    parser = argparse.ArgumentParser(description="IPMILink — IPMI Management Platform")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=3000, help="Bind port")
    parser.add_argument("--demo", action="store_true", help="Run in demo mode with simulated data")
    parser.add_argument("--config", type=str, help="Path to config.yaml")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev)")

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("serve", help="Start the server (default)")
    subparsers.add_parser("reset-password", help="Reset admin password")

    args = parser.parse_args()

    if args.demo:
        import os
        os.environ["IPMILINK_DEMO"] = "true"

    if args.config:
        import os
        os.environ["IPMILINK_CONFIG_PATH"] = args.config

    if args.command == "reset-password":
        _reset_password()
        return

    uvicorn.run(
        "backend.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


def _reset_password():
    import asyncio

    async def _do_reset():
        cfg = load_config()
        _db = Database(cfg.data.db_path)
        await _db.connect()
        am = AuthManager(_db)
        await am.initialize()

        username = input("Username: ")
        password = getpass.getpass("New password: ")
        if await am.has_user():
            await am.update_password(username, password)
            print(f"Password updated for {username}")
        else:
            await am.create_user(username, password)
            print(f"User {username} created")
        await _db.close()

    asyncio.run(_do_reset())


if __name__ == "__main__":
    cli()
