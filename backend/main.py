"""IPMIDeck — main application entry point."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import getpass
import logging
import signal
import sys
import threading
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

logger = logging.getLogger("ipmideck")

# === D-02 (04.1-04 gap-closure r3): big banner is now PERMANENTLY pinned in the console header ===
# The big ANSI Shadow banner used to be printed once on the TTY path immediately before rich
# Live(screen=True) took the alternate screen, with a SPLASH_SECONDS dwell so the operator could
# see it before it was hidden. r3 (user override of D-02 "poi compatto") moves the big banner into
# the pinned console header where it stays visible all session — so the transient pre-Live splash
# print AND the dwell were removed (flash-then-disappear was redundant/confusing). The TTY path
# still sets app.state.host_splash_shown so lifespan (D-21) does NOT double-print the banner. The
# non-TTY/Docker path is unchanged: lifespan emits the banner ONCE to `docker logs` (D-21).

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
    """Embedded uvicorn server that does NOT touch OS signal handlers (D-08).

    cli() runs this on the main thread via asyncio.run() alongside the interactive console.
    We own SIGINT/SIGTERM in cli() so a Ctrl+C / docker stop flips server.should_exit (lifespan
    shutdown runs → fans restored) instead of uvicorn pre-empting the teardown.

    Two layers are neutralised because uvicorn versions differ in HOW they capture signals:
      • install_signal_handlers() — the legacy hook (RESEARCH Pattern 3). Overridden to a no-op.
        Newer uvicorn (0.42) no longer defines it, so this override is harmless/defensive there.
      • capture_signals() — the contextmanager used by `Server.serve()` in current uvicorn. Its
        default SAVES the live SIGINT/SIGTERM handlers, installs uvicorn's own `handle_exit`, then
        on __exit__ RESTORES the saved handlers AND RE-RAISES the captured signal via
        `signal.raise_signal(...)`. That re-raise landed on cli()'s _emergency_shutdown →
        sys.exit(0) AFTER serve() returned, dumping the ugly `SystemExit: 0` +
        `asyncio.CancelledError` traceback on Ctrl+C (04.1-04 r9). On Windows the cli() graceful
        repoint via loop.add_signal_handler silently failed (ProactorEventLoop doesn't support it),
        so the emergency handler stayed installed and got hit. Overriding capture_signals() to a
        bare yield means uvicorn installs/restores/re-raises NOTHING — cli()'s signal.signal handler
        (cross-platform) owns SIGINT/SIGTERM and flips should_exit for a clean lifespan shutdown.
    """

    def install_signal_handlers(self) -> None:  # noqa: D401 — we own SIGINT/SIGTERM
        pass

    @contextlib.contextmanager
    def capture_signals(self):  # noqa: D401 — cli() owns SIGINT/SIGTERM (no capture/restore/re-raise)
        # Intentionally a plain yield: do NOT let uvicorn capture, restore, or re-raise OS signals.
        # See the class docstring — the default re-raise hit _emergency_shutdown → sys.exit(0) and
        # produced the Ctrl+C SystemExit/CancelledError traceback (r9).
        yield


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


# 08-04 (D-16): one synthetic demo server per canonical vendor. RFC5737 documentation hosts
# + synthetic throwaway creds ONLY (public repo — CLAUDE.md). Deterministic `demo-<vendor>`
# ids make the INSERT OR IGNORE seed idempotent (re-running every restart adds no duplicates).
# fanpilot_enabled is left at its default 0 — demo E2E toggles it per-vendor to exercise the
# routing / monitoring-only loop-skip journeys. (id, name, host, vendor)
_DEMO_SERVERS: list[tuple[str, str, str, str]] = [
    ("demo-dell", "Demo Dell R720", "192.0.2.10", "dell"),
    ("demo-supermicro", "Demo Supermicro X11", "192.0.2.11", "supermicro"),
    ("demo-hpe", "Demo HPE ProLiant", "192.0.2.12", "hpe"),
    ("demo-lenovo", "Demo Lenovo SR650", "192.0.2.13", "lenovo"),
    ("demo-ibm", "Demo IBM x3650 M4", "192.0.2.14", "ibm"),
    ("demo-generic", "Demo Generic BMC", "192.0.2.15", "generic"),
]


async def _seed_demo_servers(db: Database, auth: AuthManager) -> None:
    """Seed one synthetic server per canonical vendor for demo mode (D-16, SC-6).

    Idempotent: deterministic `demo-<vendor>` primary keys + `INSERT OR IGNORE` mean
    re-seeding on every restart is a no-op (no duplicate rows, no sentinel needed). Creds
    ("demo"/"demo") are throwaway and encrypted exactly as create_server does, so the rows
    are usable by the (vendor-ignoring) DemoIPMIService without ever touching real hardware.
    """
    from backend.api.server_routes import SERVER_COLORS
    from backend.core.crypto import encrypt

    key = auth.get_encryption_key()
    username_enc = encrypt("demo", key)
    password_enc = encrypt("demo", key)
    for idx, (sid, name, host, vendor) in enumerate(_DEMO_SERVERS):
        color = SERVER_COLORS[idx % len(SERVER_COLORS)]
        await db.execute(
            "INSERT OR IGNORE INTO servers "
            "(id, name, host, port, username_enc, password_enc, vendor, color) "
            "VALUES (?, ?, ?, 623, ?, ?, ?, ?)",
            (sid, name, host, username_enc, password_enc, vendor, color),
        )
    await db.commit()


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
    # connecting the DB, so the swapped-in ipmideck.db + encryption.key + config.yaml
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

    # 08-04 (D-16): in demo mode, seed one synthetic server per canonical vendor so the
    # per-vendor journeys (tier badges, monitoring-only warnings, loop-skip, argv routing)
    # are visible + Playwright-testable WITHOUT hardware. Runs AFTER auth.initialize() so the
    # encryption key is ready; idempotent (INSERT OR IGNORE on deterministic demo ids) so it
    # re-runs safely every restart. RFC5737 hosts + throwaway creds only (CLAUDE.md).
    if config.demo:
        await _seed_demo_servers(db, auth)

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
        logger.info("Demo mode active — 6 virtual servers (one per vendor) with simulated data")

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

def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the cli() argument parser (factored out so the subcommand routing is unit-testable).

    Subcommands (r7): `start` is the primary serve command; `serve` is kept as a deprecated alias;
    a bare invocation (no command) also serves. Only `reset-password` short-circuits in cli() (along
    with the --gen-cert / --reload flag early-returns). So `ipmideck start`, `ipmideck`, and
    `ipmideck --host H --port P` all reach the serve path, while `ipmideck reset-password` does not.
    Docker's `uvicorn backend.main:app` never calls cli(), so it is unaffected.
    """
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
    # `start` is the primary serve command; bare (no command) also serves.
    subparsers.add_parser("start", help="Start the server (default)")
    # `serve` kept as a deprecated alias of `start` so existing docs/scripts keep working.
    subparsers.add_parser("serve", help="Start the server (deprecated alias of `start`)")
    subparsers.add_parser("reset-password", help="Reset admin password")
    return parser


def _reexec_args(argv: list[str]) -> list[str]:
    """Strip --host/--port (and the -p alias) + their values from argv for the restart re-exec (r10).

    The restart (key 'r') re-execs a FRESH process via `python -m backend.main <args>` so it re-reads
    config.yaml — where the change-bind flow (D-15d) JUST persisted the new host/port. If we passed
    the ORIGINAL --host/--port CLI override through, the new process would re-bind the OLD value and
    the change-bind would never take effect. So this drops the bind flags (and their value tokens),
    letting config.yaml supply the bind, while keeping every OTHER arg verbatim (e.g. `start`,
    `--demo`, `--config <path>`, `--reload`).

    Handles BOTH forms:
      • space-separated  `--host 0.0.0.0`  /  `--port 8080`  /  `-p 8080`  → drop the flag AND the
        following value token.
      • combined equals  `--host=0.0.0.0`  /  `--port=8080`  /  `-p=8080`  → drop just the one token.

    Pure (returns a NEW list, never mutates argv) so it is unit-testable without any process spawn.
    The `-p` short alias is handled defensively: the current parser does not define it, but stripping
    it is harmless if absent and robust if it is ever added as a --port alias.
    """
    # Flags whose VALUE is a separate following token (space-separated form).
    _value_flags = {"--host", "--port", "-p"}
    # Combined `--flag=value` prefixes to drop as a single token.
    _equals_prefixes = ("--host=", "--port=", "-p=")

    out: list[str] = []
    skip_next = False
    for tok in argv:
        if skip_next:
            # This token is the VALUE of a just-dropped space-separated bind flag — drop it too.
            skip_next = False
            continue
        if tok in _value_flags:
            skip_next = True  # drop this flag AND its following value token
            continue
        if tok.startswith(_equals_prefixes):
            continue  # combined form: the value is in this same token, drop the whole thing
        out.append(tok)
    return out


def _do_restart(platform: str, argv_tail: list[str], execv=None, popen=None) -> None:
    """Perform the post-teardown restart action, PLATFORM-SPLIT (04.1-04 gap-closure r11).

    The caller (_serve_forever) has ALREADY run the graceful shutdown (lifespan fan-restore inside
    server.serve() — FIX-03 L1) and torn the console down (rich Live alternate screen restored) before
    calling this. This function only decides HOW to relaunch:

      • POSIX (platform != "win32"):
        os.execv replaces the process IN PLACE (same PID, controlling terminal inherited) — reliable.
        Re-exec `python -m backend.main` + _reexec_args(argv_tail) so the fresh process re-reads
        config.yaml (where change-bind persisted the new host/port) with --host/--port STRIPPED, so the
        persisted bind wins over the old CLI override. If execv raises OSError (rare: bad interpreter
        path / platform quirk), fall back to subprocess + sys.exit(0) so 'r' still restarts.

      • Windows (platform == "win32"):
        Windows has NO true exec(); os.execv is EMULATED as spawn-child + exit-parent, and for an
        INTERACTIVE console app the console/stdin handoff breaks (host UAT: pressing 'r' kept the OLD
        bind and then froze — r/ESC/Ctrl+C dead until the terminal was closed). The reliable path is the
        operator's proven manual flow: do NOT execv and do NOT spawn — print a clear relaunch hint and
        RETURN cleanly so the caller's finally (cache_task cancel, idempotent console.stop/join) runs and
        the process exits normally; the user reruns `ipmideck start` in their shell (a fresh process that
        re-reads config.yaml and binds the new host/port).

    execv/popen are INJECTABLE so this is unit-testable without a real exec or process spawn; they
    default to the real stdlib os.execv / subprocess.Popen used in production.
    """
    if platform == "win32":
        # Windows has no true exec(); emulated exec/subprocess hand the interactive console off
        # unreliably (observed: child froze, old bind retained). The reliable path is the user's
        # manual flow: exit cleanly and let the shell relaunch a fresh process (which re-reads
        # config.yaml and binds the new host/port).
        print()
        print(f"{APP_NAME}: restart required to apply the new bind.")
        print("  Run  ipmideck start  again to restart.")
        print()
        return  # caller's finally runs (teardown) → asyncio.run returns → cli() returns → clean exit

    # POSIX: in-place re-exec a fresh process with the bind flags stripped.
    import os

    if execv is None:
        execv = os.execv
    argv = [sys.executable, "-m", "backend.main"] + _reexec_args(argv_tail)
    try:
        execv(sys.executable, argv)
    except OSError as e:
        logger.error("os.execv failed (%s); falling back to subprocess", e)
        import subprocess

        if popen is None:
            popen = subprocess.Popen
        try:
            popen(argv, shell=False)
        except Exception as e2:
            logger.error("subprocess restart fallback failed (%s)", e2)
        sys.exit(0)


def _make_graceful_signal_handler(server_box: list):
    """Build the cross-platform SIGINT/SIGTERM handler used by cli() (factored out so it is unit-testable).

    Returns a ``handler(signum, frame)`` closing over ``server_box`` (a one-element list shared with
    _serve_forever, which sets server_box[0] to the live _NoSignalServer once serving):
      • server_box[0] is a live server  → flip server.should_exit = True. uvicorn exits its serve
        loop, the FastAPI lifespan shutdown runs (fans restored — FIX-03 layer 1), asyncio.run()
        returns and the process exits cleanly. No sys.exit, so no SystemExit traceback (r9).
      • server_box[0] is None (pre-serve Ctrl+C, early boot before the server object exists)
        → sys.exit(0): nothing to flip, exit cleanly (FIX-03 layer 2 — preserved).

    Installed via signal.signal (NOT loop.add_signal_handler) so it works on Windows (ProactorEventLoop
    lacks add_signal_handler) AND POSIX — that mismatch was the r9 root cause.
    """

    def _graceful_signal(signum, _frame):
        srv = server_box[0]
        if srv is not None:
            srv.should_exit = True  # graceful: uvicorn loop exits → lifespan shutdown → fan restore
        else:
            sys.exit(0)  # pre-serve: nothing to flip, exit cleanly

    return _graceful_signal


def cli():
    parser = _build_arg_parser()
    args = parser.parse_args()

    if args.demo:
        import os
        os.environ["IPMIDECK_DEMO"] = "true"

    if args.config:
        import os
        os.environ["IPMIDECK_CONFIG_PATH"] = args.config

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
    # (or IPMIDECK_CONFIG_PATH-pointed file) are silently ignored at bind time.
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
    #   yaml > hardcoded). config itself already applies IPMIDECK_SERVER_HOST/PORT
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
                    "run `ipmideck --gen-cert` first. Starting over plain HTTP.",
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

    # === FIX-03 / signal coordination (REVIEWS HIGH-4; r9 cross-platform rewrite) ===
    # ONE cross-platform handler (_make_graceful_signal_handler), installed via signal.signal so it
    # works on BOTH Windows AND POSIX (loop.add_signal_handler is unsupported on the Windows
    # ProactorEventLoop — the r9 root cause: the old repoint silently failed there, so the emergency
    # sys.exit handler stayed installed and got hit by uvicorn's capture_signals re-raise → ugly
    # SystemExit/CancelledError traceback). Three regimes, documented:
    #   1. BEFORE the server object exists (early boot / pre-serve failure): the handler sees
    #      server_box[0] is None and sys.exit(0)s so a Ctrl+C during boot still exits cleanly
    #      (FIX-03 layer 2 — preserved).
    #   2. ONCE serving (server_box[0] is the live _NoSignalServer): the SAME handler flips
    #      server.should_exit = True, so SIGINT/SIGTERM make uvicorn exit its serve loop and run the
    #      FastAPI lifespan shutdown (fans restored — FIX-03 layer 1) instead of a bare sys.exit.
    #      _NoSignalServer.capture_signals() is a no-op (see the class) so uvicorn never restores or
    #      re-raises the signal — no traceback. The KeyboardInterrupt wrapper around asyncio.run()
    #      stays as a backstop.
    #   3. The kill -9 / power-loss backstop stays the fanpilot startup-recovery query
    #      (FIX-03 layer 3) — unchanged.
    # server_box is shared with _serve_forever (it sets server_box[0] once the server is live), so the
    # handler — installed BEFORE the loop starts — flips should_exit on the live server when serving
    # and only sys.exit()s in the pre-serve window. Defined here in cli() so it can see server_box.
    server_box: list[_NoSignalServer | None] = [None]
    _graceful_signal = _make_graceful_signal_handler(server_box)
    signal.signal(signal.SIGTERM, _graceful_signal)
    signal.signal(signal.SIGINT, _graceful_signal)

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
        # server_box is the SAME one-element list cli() closed its signal handler over (r9): the
        # handler reads server_box[0] to decide should_exit-flip (serving) vs sys.exit (pre-serve).
        # We set server_box[0] to the live server inside the serve loop below.

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
            # persist to config.yaml's logging.level. IPMIDECK_LOGGING_LEVEL still wins next
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
            #
            # r7: guard the persist in try/except + logger.warning, mirroring _on_set_verbosity.
            # A file-write failure (PermissionError/OSError on a read-only/locked config.yaml) was
            # previously swallowed silently — the operator saw "restart required" with no hint the
            # persist failed. The warning is logged (and, while Live owns the screen, rendered into
            # the body via the DequeLogHandler) so a failed persist is surfaced, not lost.
            try:
                update_server_yaml({"host": host, "port": port})
            except Exception as e:
                logger.warning("Failed to persist bind %s:%d — %s", host, port, e)

        console = None
        render_thread = None
        if interactive:
            # D-24/D-07: only on a real TTY. The big ANSI Shadow banner is now PINNED PERMANENTLY
            # in the rich console header (04.1-04 gap-closure r3 — user override of D-02 "poi
            # compatto"), so there is NO transient pre-Live splash print and NO dwell here anymore:
            # the flash-then-disappear was redundant once the banner lives in the header. We STILL
            # set app.state.host_splash_shown so lifespan (D-21) does NOT also print the banner to
            # the TTY — the header already shows it, so the gate prevents a double-banner.
            app.state.host_splash_shown = True

            cur_level = (early_cfg.logging.level.upper() if early_cfg is not None else "INFO")
            scheme = "https" if (early_cfg is not None and early_cfg.server.https) else "http"

            # D-04/D-11 (04.1-04 gap-closure r4): ACTUALLY apply the initial verbosity on the
            # interactive path BEFORE the render thread starts. lifespan() does _setup_logging +
            # suppress_noisy_loggers, but that only runs LATER inside server.serve(); until then the
            # console showed "Verbosity: INFO" while DEBUG aiosqlite/uvicorn spam still flooded the
            # body — the displayed level was never enforced. Applying it here (root + handlers via
            # apply_log_level) makes the status real and tames the noise at baseline so the console
            # opens quiet. Idempotent with lifespan's later call; the 'v' toggle re-applies on demand.
            from backend.core.logging_util import apply_log_level

            apply_log_level(cur_level)
            suppress_noisy_loggers()

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
                # D-15d r5: pre-fill the change-bind editor with the CURRENT raw bind so the
                # operator edits from the value in effect. RAW host (effective_host, e.g. 0.0.0.0)
                # — NOT the browsable 127.0.0.1 get_url mapping — because this is the actual bind
                # being edited. A change-bind+restart starts a new session that recomputes
                # effective_host/port, so this naturally reflects the current bind each run.
                get_bind=lambda: (effective_host, effective_port),
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

        # r9: NO loop.add_signal_handler repoint here anymore. cli() already installed the
        # cross-platform _make_graceful_signal_handler via signal.signal BEFORE asyncio.run(); it
        # reads the shared server_box and flips should_exit once we set server_box[0] below. The old
        # add_signal_handler repoint silently failed on the Windows ProactorEventLoop (its root
        # cause), leaving the emergency sys.exit handler installed → Ctrl+C traceback.

        try:
            # SINGLE serve, then either a clean exit or a process RE-EXEC restart (r10). uvicorn
            # 0.42's serve() is single-shot and cannot be safely re-awaited in the same loop — the
            # old in-process re-serve loop rebound nothing (site unreachable on BOTH binds) and a
            # failure left the loop dead while the non-daemon render thread kept the process alive →
            # 'r'/'q'/Ctrl+C froze. We now do what the operator did by hand: serve once; on a restart
            # request, tear the console down and re-exec a FRESH process that re-reads config.yaml
            # (the change-bind persisted the new bind there). The while True stays only so the
            # structure/finally is unchanged — there is no second iteration in practice (a clean exit
            # breaks; a restart re-execs the process).
            while True:
                # Re-read config so a persisted host/port (D-15d) applies; the CLI flag still wins
                # (precedence preserved). On a restart the re-exec'd process re-reads it again with
                # the --host/--port override STRIPPED (see _reexec_args), so the persisted bind takes.
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

                await server.serve()  # full FastAPI lifespan: startup → serve → shutdown (fan restore)

                if not restart_requested[0]:
                    break  # clean exit; lifespan shutdown already ran (fans restored — FIX-03 L1)

                # RESTART requested: graceful shutdown already happened inside serve() above (the
                # lifespan fan-restore ran — FIX-03 layer 1 NOT regressed); now relaunch (platform
                # split — r11). cache_task is cancelled in finally on the way out; we also stop it here
                # so it does not linger between the teardown and the (POSIX) execv image replacement.
                logger.info("%s performing graceful restart…", APP_NAME)
                cache_task.cancel()
                # 1) Tear down the console FIRST so rich Live(screen=True) exits and the alternate
                #    screen is restored BEFORE the relaunch (otherwise the terminal is left corrupted /
                #    a Windows clean-exit message would be hidden by the Live screen). Idempotent: the
                #    finally below tolerates an already-stopped console.
                if console is not None:
                    console.stop()
                if render_thread is not None:
                    render_thread.join(timeout=5.0)
                    render_thread = None
                console = None
                # 2) Relaunch, PLATFORM-SPLIT (r11): POSIX re-execs in place via os.execv (reliable —
                #    same PID, controlling terminal inherited); Windows has no true exec() so it prints
                #    a clear "run `ipmideck start` again" hint and RETURNS (falls through to break) —
                #    emulated exec/spawn breaks the interactive console handoff (host UAT: child froze,
                #    old bind kept). On POSIX _do_restart never returns (execv replaces the image, or it
                #    exits via the subprocess fallback); on Windows it returns and we break out cleanly.
                _do_restart(platform=sys.platform, argv_tail=sys.argv[1:])
                break  # Windows: relaunch message printed; exit cleanly so the shell can relaunch.
        finally:
            cache_task.cancel()  # idempotent — already cancelled on the restart path
            if console is not None:
                console.stop()  # set _stop → render loop ends, key daemon returns
            if render_thread is not None:
                render_thread.join(timeout=5.0)

    # asyncio.run() owns the loop on the MAIN thread. The cross-platform _graceful_signal handler
    # (signal.signal, installed above) flips should_exit on Ctrl+C/SIGTERM so serve() returns and the
    # lifespan shutdown runs cleanly. This KeyboardInterrupt except stays as a BACKSTOP for any
    # SIGINT that still surfaces as a Python KeyboardInterrupt before the handler runs (it logs and
    # returns rather than letting a traceback escape) — never a bare sys.exit once serving (r9).
    try:
        asyncio.run(_serve_forever())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt — %s exiting", APP_NAME)


def _persist_logging_level(level: str) -> None:
    """Write logging.level to config.yaml (D-11 persistence). Full read-mutate-dump of the
    logging: block only, mirroring update_server_yaml. IPMIDECK_LOGGING_LEVEL wins on next boot."""
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
