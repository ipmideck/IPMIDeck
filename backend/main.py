"""IPMILink — main application entry point."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import signal
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from typing import Annotated

import uvicorn
from fastapi import Cookie, Depends, FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.staticfiles import StaticFiles

from backend.core.auth import AuthManager, require_auth
from backend.core.branding import APP_NAME, VERSION, credits_line, render_banner_safe
from backend.core.config import AppConfig, load_config, save_default_config, update_server_yaml
from backend.core.logging_util import suppress_noisy_loggers
from backend.core.database import Database
from backend.core.modules import ModuleLoader
from backend.core.websocket import WebSocketManager

logger = logging.getLogger("ipmilink")

# === D-02: launch-splash dwell ===
# The big ANSI Shadow splash is printed once on the interactive/TTY path, immediately before the
# render thread enters rich Live(screen=True) — which switches to the ALTERNATE screen buffer and
# instantly hides whatever was on the normal buffer. Without a brief pause the operator never sees
# the big banner (only the compact pinned header). We sleep SPLASH_SECONDS after emitting the
# splash + credits and BEFORE starting the render thread so "splash grande poi compatto" (D-02)
# actually happens. TTY path ONLY — the non-TTY/Docker path (D-07/D-21) emits the banner once and
# NEVER sleeps (startup must not be delayed for headless/piped/systemd).
SPLASH_SECONDS = 1.5

# === D-18: idempotent Windows-proactor ConnectionResetError suppression ===
# On Windows the ProactorEventLoop logs a full ConnectionResetError traceback when a WS/HTTP
# client drops mid-write. _silence_proactor_connreset() wraps the offending transport callback
# to swallow that one exception down to a single debug line. It is a NO-OP off Windows, and the
# module-level _PROACTOR_PATCHED guard makes it idempotent: lifespan runs again on an in-process
# restart (D-15c), so without the guard the method would be wrapped repeatedly (REVIEWS MED).
_PROACTOR_PATCHED = False


def _silence_proactor_connreset() -> None:
    """Tame the Windows proactor ConnectionResetError spam (D-18). No-op off Windows + idempotent."""
    global _PROACTOR_PATCHED
    if sys.platform != "win32" or _PROACTOR_PATCHED:
        return
    from asyncio.proactor_events import _ProactorBasePipeTransport

    orig = _ProactorBasePipeTransport._call_connection_lost

    def _wrap(self, exc):
        try:
            return orig(self, exc)
        except ConnectionResetError:
            logger.debug("WS/HTTP client dropped (ConnectionReset) — suppressed")

    _ProactorBasePipeTransport._call_connection_lost = _wrap
    _PROACTOR_PATCHED = True


class _NoSignalServer(uvicorn.Server):
    """Embedded uvicorn server that does NOT install its own signal handlers (D-08).

    cli() runs this on the main thread via asyncio.run() alongside the interactive console.
    We own SIGINT/SIGTERM in cli() so a Ctrl+C / docker stop flips server.should_exit (lifespan
    shutdown runs → fans restored) instead of uvicorn pre-empting the teardown. Overriding
    install_signal_handlers() to a no-op is the documented pattern (RESEARCH Pattern 3).
    """

    def install_signal_handlers(self) -> None:  # noqa: D401 — we own SIGINT/SIGTERM
        pass


# === Global app state (set during lifespan) ===
# NOTE: the EventBus was removed in 04-W6-01 (see backend/core/events.py tombstone).
# Module dependency injection now flows through backend.modules.ModuleContext via
# set_ctx()/get_ctx() (Decision J) instead of the former `import backend.modules as ctx`
# mutable-globals pattern.
config: AppConfig = AppConfig()
db: Database = Database("")
auth: AuthManager = AuthManager(db)
ws_manager: WebSocketManager = WebSocketManager()
module_loader: ModuleLoader = ModuleLoader(db)
ipmi_service = None  # Set during startup based on config.demo


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def print_banner_safe(text: str) -> None:
    """Emit a (possibly Unicode-block) banner to stdout WITHOUT crashing on a non-UTF-8 stream.

    The ANSI Shadow splash (backend.core.branding.banner) is drawn from Unicode block/box chars
    (█ ╗ ═ ║ ╝ ╚ ╔). On a REAL interactive Windows console Python writes via WriteConsoleW so those
    print fine, but when stdout is PIPED/redirected on Windows the stream encoding is cp1252 and a
    bare ``print(text)`` raises UnicodeEncodeError. This helper makes the emission encoding-safe:

      1. Fast path — try a normal ``print(text)``. Succeeds on a UTF-8 stream or a real Win console.
      2. On UnicodeEncodeError — re-emit the same bytes as UTF-8 directly to the underlying binary
         buffer (``sys.stdout.buffer``), so the block art survives a cp1252/ascii-encoded pipe.
      3. If even that is unavailable (no .buffer, closed stream, etc.) — degrade to plain ASCII
         (render_banner_safe / APP_NAME) so the process NEVER dies just trying to print a banner.

    Import-safe on Linux (pure stdlib, no platform imports) and does nothing to TTY-gating — callers
    still decide WHEN to emit; this only governs HOW the bytes hit a non-UTF-8 stream.
    """
    try:
        print(text)
        return
    except UnicodeEncodeError:
        pass
    # cp1252/ascii pipe: write UTF-8 bytes straight to the binary buffer (bypasses the text codec).
    try:
        buf = sys.stdout.buffer  # type: ignore[attr-defined]
        buf.write((text + "\n").encode("utf-8"))
        buf.flush()
        return
    except Exception:
        # Last-ditch: a plain-ASCII brand so we still announce ourselves without ever crashing.
        try:
            print(render_banner_safe())
        except Exception:
            print(APP_NAME)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    global config, db, auth, ws_manager, module_loader, ipmi_service

    # Load config
    config = load_config()
    _setup_logging(config.logging.level)

    # D-04: keep the INFO default clean — tame uvicorn.access etc. at the INFO baseline so
    # "quiet == INFO with noisy loggers suppressed" holds in Docker too (idempotent on restart).
    suppress_noisy_loggers()

    # D-18: install the idempotent Windows-proactor ConnectionReset suppression early, before any
    # WS/HTTP traffic. No-op off Windows; the _PROACTOR_PATCHED guard makes it safe across restarts.
    _silence_proactor_connreset()

    # D-21: emit the branded banner ONCE via a TTY-independent print/log so it shows in
    # `docker logs` (the container never runs cli()). Gated on app.state.host_splash_shown:
    # cli() sets that flag ONLY on the interactive TTY path, where the rich splash (Task 2)
    # already shows the banner — so the host TTY never double-prints (REVIEWS MED: no-double-banner).
    # On Docker / non-TTY the flag is unset → the operator gets the banner here.
    if not getattr(app.state, "host_splash_shown", False):
        # render_banner_safe() degrades the figlet on a broken pyfiglet install; print_banner_safe()
        # degrades the EMISSION on a cp1252/piped stdout (the ANSI Shadow block chars would otherwise
        # raise UnicodeEncodeError under `docker logs`/redirected non-UTF-8 streams).
        print_banner_safe(render_banner_safe())  # render-safe figlet art; Docker logs capture it
        logger.info("%s", credits_line())  # credits via logger (INFO — visible by default, D-04)

    if config.demo:
        logger.info("*** DEMO MODE — no real hardware ***")

    # Save default config if missing
    data_dir = Path(config.data.db_path).parent
    save_default_config(data_dir / "config.yaml")

    # 04-W6-03: apply a pending restore (staged by POST /api/system/restore) BEFORE
    # connecting the DB, so the swapped-in ipmilink.db + encryption.key + config.yaml
    # are the ones that get opened this boot. No-op when data/staging/ is absent.
    from backend.api.system_routes import _apply_staging_if_present
    if await _apply_staging_if_present(config):
        logger.info("Applied restore staging swap on startup")

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

    # 04-W6-02 / Decision J: construct the explicit ModuleContext and install it via
    # set_ctx(). Modules look it up FRESH at function-use time via get_ctx() — never
    # bound at import time. Replaces the former mutable-globals injection
    # (modules_pkg.db = db, ...). The EventBus is gone (04-W6-01), so ctx has no
    # `events` field.
    from backend.modules import ModuleContext, set_ctx
    ctx = ModuleContext(db=db, ipmi=ipmi_service, ws=ws_manager, config=config)
    set_ctx(ctx)

    # GAP-05: read persisted per-module enable state (written by ModuleLoader.set_enabled
    # via db.set_config) so a UI-disabled module stays disabled across restarts. No
    # prefix-scan helper exists on Database, so query each built-in id explicitly.
    persisted_enabled: dict[str, bool] = {}
    for mod_id in ModuleLoader.BUILTIN_MODULES:
        raw = await db.get_config(f"modules.{mod_id}.enabled")
        if raw is not None:
            persisted_enabled[mod_id] = raw.strip().lower() != "false"

    # Load modules (discover, run migrations, run setup hooks)
    module_loader = ModuleLoader(db)
    await module_loader.discover_and_load(
        ctx, config.modules, persisted_enabled=persisted_enabled
    )

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
    logger.info("%s started on %s:%d", APP_NAME, effective_host, effective_port)
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
    title=APP_NAME,
    version=VERSION,
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
    parser = argparse.ArgumentParser(description=f"{APP_NAME} — IPMI Management Platform")
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

    # ============================================================================
    # BIND PRECEDENCE (documented contract — D-15d correction):
    #   effective_host/port (computed above) = explicit CLI flag > config (env >
    #   yaml > hardcoded). config itself already applies IPMILINK_SERVER_HOST/PORT
    #   over yaml (see config._apply_env_overrides). So a value persisted to
    #   config.yaml by the menu's change-bind action (D-15d) is OVERRIDDEN by an
    #   env var or a CLI --host/--port on the next boot — env/CLI always win. The
    #   Docker bind is unaffected: the container's CMD passes --host/--port argv
    #   and never executes cli(), so a bad persisted config value cannot break it.
    # ============================================================================

    # === --reload dev fast path (REVIEWS MED) ===
    # --reload needs uvicorn's own process supervisor (a reloader parent process),
    # which is incompatible with the embedded uvicorn.Server/Config model below.
    # When --reload is requested we fall back to the ORIGINAL uvicorn.run(reload=True)
    # path and SKIP the console entirely: no port guard rewrite, no _NoSignalServer,
    # no key listener. --reload is dev-only and intentionally bypasses the interactive
    # console + single-instance guard.
    if args.reload:
        uvicorn_kwargs = dict(
            host=effective_host, port=effective_port, reload=True, log_level="info"
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
        return

    # Lazy import (E402-clean): the console module is the high-risk rich/keypress
    # surface; import it only on the serve path, after the TTY-independent fast
    # paths (reset-password / gen-cert / --reload) have already returned.
    from backend.console import (
        ConsoleUI,
        browsable_url,
        is_interactive,
        port_in_use,
        start_key_listener,
    )

    # === Single-instance guard with error distinction (D-17 + REVIEWS MED) ===
    # Distinguish "port already in use" (a second backend — refuse, don't fight over
    # the BMC) from "address unavailable / not permitted" (bad host, IPv6-only,
    # privileged port). port_in_use() returns True for the EADDRINUSE case; for the
    # address-unavailable case we attempt the bind here and inspect errno/winerror.
    if port_in_use(effective_host, effective_port):
        print(
            f"ERROR: {APP_NAME} refused to start — port {effective_port} is already "
            f"in use on {effective_host} (another instance may be running).",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        # Probe the actual bind once to surface address-unavailable / not-permitted
        # errors with a DISTINCT message (EADDRNOTAVAIL / WSAEADDRNOTAVAIL / EACCES).
        import errno as _errno
        import socket as _socket

        _probe_host = (
            "127.0.0.1" if effective_host in ("0.0.0.0", "::", "") else effective_host
        )
        _probe = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        try:
            _probe.bind((_probe_host, effective_port))
        except OSError as e:
            _eno = getattr(e, "errno", None)
            _werr = getattr(e, "winerror", None)
            _addr_unavailable = (
                _eno in (_errno.EADDRNOTAVAIL, _errno.EACCES)
                or _werr in (10049, 10013)  # WSAEADDRNOTAVAIL / WSAEACCES
            )
            if _addr_unavailable:
                print(
                    f"ERROR: {APP_NAME} cannot bind {effective_host}:{effective_port} — "
                    f"address unavailable or not permitted.",
                    file=sys.stderr,
                )
            else:
                # An EADDRINUSE we lost the race to, or any other bind failure → in use.
                print(
                    f"ERROR: {APP_NAME} refused to start — port {effective_port} is already "
                    f"in use on {effective_host} (another instance may be running).",
                    file=sys.stderr,
                )
            sys.exit(1)
        finally:
            _probe.close()

    # === FIX-03 / signal coordination (REVIEWS HIGH-4) ===
    # Three regimes, documented:
    #   1. BEFORE the server object exists (early boot / pre-serve failure): the
    #      belt-and-suspenders _emergency_shutdown handlers below sys.exit(0) so a
    #      Ctrl+C during boot still exits cleanly. (FIX-03 layer 2 — preserved.)
    #   2. ONCE serving: the handlers are REPOINTED (not removed) to flip
    #      server.should_exit on the loop via call_soon_threadsafe, so SIGINT/SIGTERM
    #      run the FastAPI lifespan shutdown (fans restored — FIX-03 layer 1) instead
    #      of a bare sys.exit. On Windows we additionally rely on _NoSignalServer +
    #      a KeyboardInterrupt wrapper around asyncio.run() (the ProactorEventLoop
    #      lacks add_signal_handler for SIGTERM).
    #   3. The kill -9 / power-loss backstop stays the fanpilot startup-recovery query
    #      (FIX-03 layer 3) — unchanged.
    def _emergency_shutdown(signum, _frame):
        logger.warning(
            "Signal %d received before uvicorn lifespan started — exiting", signum
        )
        sys.exit(0)

    signal.signal(signal.SIGTERM, _emergency_shutdown)
    signal.signal(signal.SIGINT, _emergency_shutdown)

    # SSL kwargs shared by every restart iteration (recomputed below per-iteration so
    # a persisted https flip is picked up on restart, but cert/key paths rarely change).
    interactive = is_interactive()

    async def _serve_forever() -> None:
        """Main-thread asyncio entry: own the loop, run the console on a side thread,
        and run uvicorn via an embedded _NoSignalServer with a should_exit-driven
        exit/restart loop so every teardown flows through the FastAPI lifespan (D-08/D-12/D-15c).
        """
        loop = asyncio.get_running_loop()
        # restart_requested is a one-element list so the closures below can mutate it
        # without `nonlocal` gymnastics across the nested callback scopes.
        restart_requested = [False]
        server_box: list[_NoSignalServer | None] = [None]

        # --- loop-maintained cached server snapshot (REVIEWS MED, integration_design A) ---
        # get_servers() is called from console.dispatch (which runs ON this loop via
        # call_soon_threadsafe). Calling asyncio.run() there would deadlock, and scheduling
        # a coroutine onto the loop FROM the loop is awkward — so a tiny background task
        # refreshes a plain-list cache and get_servers() returns it read-only.
        servers_cache: list[dict] = []

        async def _refresh_servers_cache() -> None:
            while True:
                try:
                    rows = await db.fetchall(
                        "SELECT name, host, is_online FROM servers ORDER BY name"
                    )
                    servers_cache.clear()
                    for r in rows:
                        servers_cache.append(
                            {
                                "name": r["name"],
                                "host": r["host"],
                                "status": "online" if r["is_online"] else "offline",
                            }
                        )
                except Exception:
                    # DB may not be connected yet on the first ticks — ignore and retry.
                    pass
                await asyncio.sleep(5)

        cache_task = asyncio.create_task(_refresh_servers_cache())

        # --- console callbacks (all run ON the loop thread; never mutate server.* off-loop) ---
        def _request_exit() -> None:
            srv = server_box[0]
            if srv is not None:
                srv.should_exit = True

        def _request_restart() -> None:
            srv = server_box[0]
            restart_requested[0] = True
            if srv is not None:
                srv.should_exit = True

        def _on_set_verbosity(level: str) -> None:
            # D-11/D-25: apply at runtime (basicConfig is a no-op once handlers exist) AND
            # persist to config.yaml's logging.level. IPMILINK_LOGGING_LEVEL still wins next
            # boot (env > yaml — see config._apply_env_overrides), documented above.
            from backend.core.logging_util import apply_log_level

            apply_log_level(level)
            try:
                _persist_logging_level(level)
            except Exception:
                logger.warning("Could not persist logging level %s", level)

        def _on_change_bind(host: str, port: int) -> None:
            # D-15d: persist host/port to config.yaml's server block. Applies on the NEXT
            # restart (the console already told the operator "restart required"). env/CLI
            # still override on boot (documented above).
            update_server_yaml({"host": host, "port": port})

        console = None
        render_thread = None
        if interactive:
            # D-24/D-07: only on a real TTY. Print the rich splash ONCE and set the
            # app.state gate so lifespan (Task 1) skips its banner → no double banner.
            from backend.core.branding import banner, credits_line

            # banner() is the big ANSI Shadow splash (Unicode block art); print_banner_safe()
            # guarantees it never raises UnicodeEncodeError if this TTY's stdout is a cp1252 pipe.
            print_banner_safe(banner())
            print(credits_line())
            app.state.host_splash_shown = True

            # D-02: dwell on the big splash before rich Live (alternate screen) hides it, so the
            # operator actually sees "splash grande poi compatto". TTY path only — the non-TTY
            # branch below never reaches this sleep (D-07/D-21: banner once, no startup delay).
            time.sleep(SPLASH_SECONDS)

            cur_level = (early_cfg.logging.level.upper() if early_cfg is not None else "INFO")
            scheme = "https" if (early_cfg is not None and early_cfg.server.https) else "http"

            console = ConsoleUI(
                ws_manager=ws_manager,
                # D-15a: map a wildcard bind (0.0.0.0/::/"") to a browsable 127.0.0.1 so 'u'
                # surfaces a URL the operator can actually open (not http://0.0.0.0:port).
                get_url=lambda: browsable_url(scheme, effective_host, effective_port),
                get_servers=lambda: list(servers_cache),  # D-15b — cached snapshot (async-safe)
                on_exit=lambda: loop.call_soon_threadsafe(_request_exit),  # D-12
                on_restart=lambda: loop.call_soon_threadsafe(_request_restart),  # D-15c
                on_set_verbosity=_on_set_verbosity,  # D-11/D-25 (dispatch already on-loop)
                on_change_bind=_on_change_bind,  # D-15d
                verbosity=cur_level,
            )
            # Render loop on a DEDICATED (non-daemon) thread; key listener on a DAEMON
            # thread that marshals each key onto the loop via call_soon_threadsafe.
            render_thread = threading.Thread(target=console.run, daemon=False)
            render_thread.start()
            start_key_listener(loop, console.dispatch, stop_event=console._stop)
        else:
            # Non-TTY (Docker uvicorn-direct never reaches cli(); piped/headless host):
            # banner already emitted in lifespan (Task 1). No key listener, no rich.Live,
            # no busy-spin (D-07/D-24). Just serve plainly.
            pass

        # Repoint the signal handlers now that we have a live loop: flip should_exit so
        # lifespan shutdown runs (fan restore) instead of bare sys.exit (regime 2 above).
        def _signal_to_should_exit() -> None:
            srv = server_box[0]
            if srv is not None:
                srv.should_exit = True

        for _sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(_sig, _signal_to_should_exit)
            except (NotImplementedError, RuntimeError):
                # Windows ProactorEventLoop lacks add_signal_handler for SIGTERM — the
                # KeyboardInterrupt wrapper around asyncio.run() (in cli()) handles Ctrl+C
                # by flipping should_exit on the live server instead.
                pass

        try:
            while True:
                # Re-read config each iteration so a persisted host/port (D-15d) applies on
                # restart; the CLI flag still wins (precedence preserved).
                iter_cfg = load_config()
                iter_host = (
                    args.host if args.host is not None else iter_cfg.server.host
                )
                iter_port = (
                    args.port if args.port is not None else iter_cfg.server.port
                )
                app.state.effective_host = iter_host
                app.state.effective_port = iter_port

                cfg_kwargs: dict = {}
                if iter_cfg.server.https and iter_cfg.server.cert_file and iter_cfg.server.key_file:
                    cfg_kwargs["ssl_certfile"] = iter_cfg.server.cert_file
                    cfg_kwargs["ssl_keyfile"] = iter_cfg.server.key_file

                uconfig = uvicorn.Config(
                    "backend.main:app",
                    host=iter_host,
                    port=iter_port,
                    log_level="info",
                    **cfg_kwargs,
                )
                server = _NoSignalServer(uconfig)
                server_box[0] = server
                restart_requested[0] = False

                await server.serve()  # runs the FULL FastAPI lifespan (startup fans, etc.)

                if not restart_requested[0]:
                    break  # clean exit → lifespan shutdown already ran (fans restored)
                logger.info("%s restarting in-process…", APP_NAME)
        finally:
            cache_task.cancel()
            if console is not None:
                console.stop()  # set _stop → render loop ends, key daemon returns
            if render_thread is not None:
                render_thread.join(timeout=5.0)

    # asyncio.run() owns the loop on the MAIN thread. A KeyboardInterrupt (Ctrl+C on
    # Windows, where add_signal_handler(SIGTERM) is unavailable) is translated into a
    # clean teardown by flipping should_exit — never a bare sys.exit once serving.
    try:
        asyncio.run(_serve_forever())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt — %s exiting", APP_NAME)


def _persist_logging_level(level: str) -> None:
    """Write logging.level to config.yaml (D-11 persistence). Full read-mutate-dump of the
    logging: block only, mirroring update_server_yaml. IPMILINK_LOGGING_LEVEL wins on next boot."""
    import yaml

    from backend.core.config import _config_yaml_path

    path = _config_yaml_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw: dict = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    log_block = raw.get("logging")
    if not isinstance(log_block, dict):
        log_block = {}
    log_block["level"] = level.lower()
    raw["logging"] = log_block
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(raw, f, default_flow_style=False, sort_keys=False)


def _reset_password():
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
