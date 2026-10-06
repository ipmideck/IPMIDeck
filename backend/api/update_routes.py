"""Version history and update-check routes.

Split into two routers on purpose. The changelog and the cached state never touch the network, so
they are always available. Anything that can open a socket lives on the second router, which
``backend.main`` registers **only** when the operator has left ``updates.enabled`` on. With it
off the endpoint does not exist — suppression is a missing route rather than a runtime branch
that a later refactor could quietly step past.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.core.auth import require_auth
from backend.core.branding import VERSION
from backend.core.updates import (
    CHANGELOG_URL,
    RELEASES_URL,
    parse_changelog,
    read_changelog_text,
)

# Always mounted — offline-only.
router = APIRouter()

# Mounted only when the configuration permits an outbound request.
network_router = APIRouter()


@router.get("/changelog", dependencies=[Depends(require_auth)])
async def get_changelog():
    """The packaged version history, parsed into entries.

    Reads a file that shipped inside the package. This is what makes the history readable on an
    instance that has never had, and will never have, a route to the internet.
    """
    entries = parse_changelog(read_changelog_text())
    return {
        "success": True,
        "current_version": VERSION,
        "changelog_url": CHANGELOG_URL,
        "releases_url": RELEASES_URL,
        "entries": [entry.as_dict() for entry in entries],
    }


@router.get("/state", dependencies=[Depends(require_auth)])
async def get_update_state():
    """What is known about updates right now, without asking anyone.

    ``enabled`` reports the configuration switch and ``consent`` the operator's own answer, so
    the interface can explain precisely why a control is inactive instead of showing a dead
    button.
    """
    from backend.main import config, update_service

    status = await update_service.cached_status()
    plan = _plan(status) if status.update_available else None
    return {
        "success": True,
        "enabled": config.updates.enabled,
        "consent": await update_service.consent_given(),
        **status.as_dict(),
        "upgrade": plan.public() if plan else None,
    }


def _watchtower(config) -> tuple[str, str] | None:
    url, token = config.updates.watchtower_url, config.updates.watchtower_token
    if not (isinstance(url, str) and isinstance(token, str) and url.strip() and token.strip()):
        return None
    if not url.strip().lower().startswith(("http://", "https://")):
        return None
    return url.strip(), token.strip()


def _plan(status):
    """How the version on offer would be installed on this copy, as of now."""
    from backend.core.update_install import plan_for
    from backend.main import _app_control, config

    return plan_for(
        status.install_method,
        status.latest_version if status.update_available else None,
        watchtower=_watchtower(config) is not None,
        can_restart=_app_control["restart"] is not None,
        can_exit=_app_control["exit"] is not None,
    )


class ConsentBody(BaseModel):
    """Whether IPMIDeck may check for a newer version on its own."""

    enabled: bool


@network_router.post("/check", dependencies=[Depends(require_auth)])
async def check_for_updates():
    """Check now. This is an explicit operator action, so it does not require the standing
    consent that the unattended check does — but it is still gated by the configuration switch,
    which is why it lives on this router."""
    from backend.main import update_service

    status = await update_service.check_now()
    return {"success": status.error is None, **status.as_dict()}


@network_router.post("/install")
async def install_update(user: str = Depends(require_auth)):
    """Install the newer version the last check found, the way this copy was installed.

    Takes no input: the version is the one this server found on the official channel, and the
    way to install it is decided by the install itself. Refused in demo mode and with the login
    switched off, since this replaces the running program.
    """
    from backend.core.config import _config_yaml_path
    from backend.core.update_install import installer
    from backend.main import _app_control, auth, config, update_service

    if config.demo:
        return {"success": False, "error_code": "update_demo"}
    if not await auth.is_auth_enabled():
        return {"success": False, "error_code": "update_needs_login"}
    status = await update_service.cached_status()
    if not status.update_available or not status.latest_version:
        return {"success": False, "error_code": "update_no_update"}
    db_path = Path(config.data.db_path)
    return await installer.start(
        plan=_plan(status),
        target=status.latest_version,
        db_path=db_path,
        data_dir=db_path.parent,
        config_path=_config_yaml_path(),
        restart=_app_control["restart"],
        exit_app=_app_control["exit"],
        watchtower=_watchtower(config),
        user=user,
    )


@network_router.get("/install", dependencies=[Depends(require_auth)])
async def update_install_state():
    """Where the update started from the web UI has got to."""
    from backend.core.update_install import installer

    return {"success": True, **installer.snapshot()}


@network_router.put("/consent", dependencies=[Depends(require_auth)])
async def set_update_consent(body: ConsentBody):
    """Record whether the unattended check may run, and start or stop it immediately.

    Taking effect without a restart is the point: an operator who turns this off has to be right
    about it straight away.
    """
    from backend.main import update_service

    await update_service.apply_consent(body.enabled)
    return {"success": True, "enabled": body.enabled, "running": update_service.running()}
