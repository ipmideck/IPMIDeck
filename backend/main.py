"""IPMILink — main application entry point."""

from __future__ import annotations

import argparse
import getpass
import logging
import signal
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from typing import Annotated

import uvicorn
from fastapi import Cookie, Depends, FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.staticfiles import StaticFiles

from backend.core.auth import AuthManager, require_auth
from backend.core.config import AppConfig, load_config, save_default_config, update_server_yaml
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

    # GAP-05: read persisted per-module enable state (written by ModuleLoader.set_enabled
    # via db.set_config) so a UI-disabled module stays disabled across restarts. No
    # prefix-scan helper exists on Database, so query each built-in id explicitly.
    persisted_enabled: dict[str, bool] = {}
    for mod_id in ModuleLoader.BUILTIN_MODULES:
        raw = await db.get_config(f"modules.{mod_id}.enabled")
        if raw is not None:
            persisted_enabled[mod_id] = raw.strip().lower() != "false"

    # Load modules (discover, run migrations, register events)
    module_loader = ModuleLoader(db, event_bus)
    await module_loader.discover_and_load(config.modules, persisted_enabled=persisted_enabled)

    # FIX-04: dynamically mount only enabled modules' routes (with auth guard).
    # Disabled modules will never have their routes registered → 404 instead of 200.
    # IMPORTANT: must happen BEFORE the SPA fallback route is registered so FastAPI
    # routes module paths correctly (catch-all "/{full_path:path}" would shadow them).
    module_loader.mount_routes(app, dependencies=[Depends(require_auth)])

    # Register SPA fallback AFTER all API routes (including dynamically mounted modules).
    # The catch-all /{full_path:path} must come last or it shadows module routes.
    _mount_spa(app)

    # Start module background tasks
    await module_loader.start_background_tasks()

    # Prefer effective bind values stashed by cli() (which applies CLI precedence
    # over config). Fall back to config values when uvicorn is launched directly
    # (e.g. from a test harness) without going through cli().
    effective_host = getattr(app.state, "effective_host", None) or config.server.host
    effective_port = getattr(app.state, "effective_port", None) or config.server.port
    logger.info("IPMILink started on %s:%d", effective_host, effective_port)
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
async def websocket_endpoint(
    websocket: WebSocket,
    session: Annotated[str | None, Cookie()] = None,
):
    # 04-W4-01 auth gate: when auth is ENABLED, a valid session cookie is required
    # BEFORE the handshake is accepted. When auth is DISABLED (open-access mode, or
    # no user configured), the connection is allowed exactly as before — this mirrors
    # require_auth's is_auth_enabled() gate so single-user no-auth setups are never
    # locked out. Uses the current module globals (auth, db, ws_manager) — there is
    # NO app-state container exists (Decision A1 — Codex HIGH fix).
    if await auth.is_auth_enabled():
        username = auth.verify_session_token(session) if session else None
        if not username:
            # Reject pre-accept with policy-violation close code (1008).
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        # Phase 02.1 REVIEWS #7 invariant: a token signed for an OLD username (pre
        # credential-replace) must not stay valid — confirm the token subject is the
        # CURRENT single stored user, same check as require_auth.
        row = await db.fetchone(
            "SELECT 1 FROM users WHERE username = ? LIMIT 1", (username,)
        )
        if row is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    # Authenticated (or auth disabled) → accept + replay snapshot. The early-return
    # above is added BEFORE connect(), so the snapshot-replay ordering is unchanged.
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
app.include_router(server_router, prefix="/api/servers", tags=["Servers"], dependencies=[Depends(require_auth)])
app.include_router(system_router, prefix="/api", tags=["System"])
app.include_router(dashboard_router, prefix="/api/dashboard", tags=["Dashboard"], dependencies=[Depends(require_auth)])
app.include_router(module_router, prefix="/api/admin/modules", tags=["Modules"], dependencies=[Depends(require_auth)])


def _mount_spa(app: FastAPI) -> None:
    """Register static file serving and SPA fallback route.

    Called at the END of lifespan startup, AFTER all API routes (including
    dynamically mounted module routes) are registered. The catch-all
    /{full_path:path} route must be last — any route registered after it is
    unreachable because FastAPI matches routes in registration order.
    """
    static_dir = Path(__file__).parent / "static"
    if not static_dir.exists():
        return

    from fastapi.responses import FileResponse

    # Serve static assets (JS, CSS, images) directly
    if (static_dir / "assets").exists():
        try:
            app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="static-assets")
        except Exception:
            pass  # Already mounted (e.g., during --reload; ignore duplicate)

    # SPA fallback: non-API routes return index.html for React Router.
    # API paths (/api/*) that don't match a registered route return 404 —
    # this is critical for FIX-04: disabled modules must return 404, not 200.
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        from fastapi import HTTPException

        # Reject unmatched /api/* paths so disabled modules return 404 (not SPA).
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")

        # Try to serve the exact file first (favicon.svg, etc.)
        file_path = static_dir / full_path
        if full_path and file_path.is_file():
            return FileResponse(file_path)
        # Otherwise return index.html for React Router
        return FileResponse(static_dir / "index.html")


# === CLI entry point ===

def cli():
    parser = argparse.ArgumentParser(description="IPMILink — IPMI Management Platform")
    # default=None sentinels — lets us detect whether the user explicitly passed
    # --host/--port so config.yaml can supply the value when the flag is absent.
    parser.add_argument("--host", default=None, help="Bind host (default from config.yaml or 0.0.0.0)")
    parser.add_argument("--port", type=int, default=None, help="Bind port (default from config.yaml or 3000)")
    parser.add_argument("--demo", action="store_true", help="Run in demo mode with simulated data")
    parser.add_argument("--config", type=str, help="Path to config.yaml")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev)")
    parser.add_argument(
        "--gen-cert",
        action="store_true",
        help="Generate a self-signed cert+key pair under data/certs/, write the paths to "
             "config.yaml, and exit. Set server.https=true to enable HTTPS.",
    )

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

    if args.gen_cert:
        # 04-W4-03: generate a self-signed pair under data/certs/, persist the paths to
        # config.yaml's server section, then exit. The operator flips server.https=true
        # (here in config.yaml or via the Settings Network card) and restarts.
        from backend.core.certs import generate_self_signed
        cfg = load_config()
        cert_dir = Path(cfg.data.db_path).parent / "certs"
        cert_path, key_path = generate_self_signed(cert_dir)
        update_server_yaml({"cert_file": str(cert_path), "key_file": str(key_path)})
        print(f"Generated: {cert_path}")
        print(f"Generated: {key_path}")
        print("Wrote cert_file/key_file to config.yaml. Set server.https=true and restart "
              "to serve over HTTPS.")
        return

    # === FIX-02 gap closure: load config BEFORE uvicorn.run() ===
    # Without this, uvicorn binds using argparse defaults (or None) before
    # lifespan() ever calls load_config(), so server.host/port from config.yaml
    # (or IPMILINK_CONFIG_PATH-pointed file) are silently ignored at bind time.
    # lifespan() still calls load_config() again — that is idempotent and
    # intentional (lifespan needs an AppConfig for module setup regardless of
    # how uvicorn was bound, e.g., when running via `uvicorn backend.main:app`).
    try:
        early_cfg = load_config()
    except Exception as e:
        # If config is malformed, fall back to hardcoded defaults so the
        # server can still start and surface the error during lifespan.
        # Logging is not yet configured here, so use print to stderr.
        print(f"WARNING: early config load failed ({e}); using CLI/hardcoded defaults for bind", file=sys.stderr)
        early_cfg = None

    # Precedence: explicit CLI flag > config (which itself = env var > yaml > hardcoded) > hardcoded fallback.
    # argparse default=None means args.host/args.port is None iff the user did NOT pass the flag.
    effective_host = args.host if args.host is not None else (early_cfg.server.host if early_cfg is not None else "0.0.0.0")
    effective_port = args.port if args.port is not None else (early_cfg.server.port if early_cfg is not None else 3000)

    # Stash the resolved bind values on app.state so lifespan() can log them.
    # Without this, the startup log line would print config.server.host/port and
    # lie when CLI flags override config (e.g. --port 8080 with config :9999).
    # lifespan() reads via getattr(..., None) so a direct uvicorn invocation
    # (no cli()) still falls back to config.server.* correctly.
    app.state.effective_host = effective_host
    app.state.effective_port = effective_port

    # === FIX-03 layer 2: belt-and-suspenders signal handlers ===
    # Uvicorn installs its own SIGTERM/SIGINT handlers when it boots and triggers
    # the lifespan shutdown (which restores fans via fanpilot_shutdown — layer 1).
    # These handlers ONLY fire if uvicorn never reaches that stage (e.g., bind error,
    # config load error). They log+exit so the OS doesn't terminate uncleanly.
    # The actual safety net for kill -9 / power loss is the startup recovery query
    # in fanpilot/tasks.py:fanpilot_loop (layer 3).
    def _emergency_shutdown(signum, _frame):
        logger.warning(
            "Signal %d received before uvicorn lifespan started — exiting", signum
        )
        sys.exit(0)

    signal.signal(signal.SIGTERM, _emergency_shutdown)
    signal.signal(signal.SIGINT, _emergency_shutdown)

    # 04-W4-03: when config.server.https is on, hand uvicorn the configured cert/key so it
    # terminates TLS. Paths come from early_cfg (env > yaml). Missing files surface as a
    # uvicorn startup error rather than silently falling back to HTTP.
    uvicorn_kwargs = dict(
        host=effective_host,
        port=effective_port,
        reload=args.reload,
        log_level="info",
    )
    if early_cfg is not None and early_cfg.server.https:
        if not early_cfg.server.cert_file or not early_cfg.server.key_file:
            print(
                "WARNING: server.https=true but cert_file/key_file are not set in config.yaml; "
                "run `ipmilink --gen-cert` first. Starting over plain HTTP.",
                file=sys.stderr,
            )
        else:
            uvicorn_kwargs["ssl_certfile"] = early_cfg.server.cert_file
            uvicorn_kwargs["ssl_keyfile"] = early_cfg.server.key_file

    uvicorn.run("backend.main:app", **uvicorn_kwargs)


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
