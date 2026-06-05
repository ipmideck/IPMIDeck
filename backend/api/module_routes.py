"""Module management routes — list, enable, disable modules."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.core.i18n import get_lang, t

router = APIRouter()


class ModuleToggle(BaseModel):
    enabled: bool


@router.get("")
async def list_modules():
    from backend.main import module_loader
    modules = []
    for mod in module_loader.get_all_modules():
        modules.append({
            "id": mod.id,
            "name": mod.name,
            "version": mod.version,
            "description": mod.description,
            "author": mod.author,
            "category": mod.category,
            "icon": mod.icon,
            "enabled": module_loader.is_enabled(mod.id),
            "dependencies": mod.dependencies,
            "widgets": mod.widgets,
        })
    return {"modules": modules}


@router.put("/{module_id}")
async def toggle_module(module_id: str, body: ModuleToggle, lang: str = Depends(get_lang)):
    from backend.main import module_loader
    mod = module_loader.get_module(module_id)
    if not mod:
        return {"success": False, "error": t("module_not_found", lang)}
    await module_loader.set_enabled(module_id, body.enabled)
    if body.enabled:
        started = await module_loader.start_module(module_id)
        # started is False when the module was disabled at process startup:
        # its migrations/event-subscriptions/routes were never set up this
        # process, so tasks must NOT run until a restart.
        return {
            "success": True,
            "module_id": module_id,
            "enabled": True,
            "restart_required": not started,
        }
    else:
        stopped_dependents = await module_loader.stop_module(module_id)
        # stopped_dependents lists modules cascade-stopped because they depend
        # on this one (e.g. ["fanpilot"] when disabling "sensors").
        return {
            "success": True,
            "module_id": module_id,
            "enabled": False,
            "stopped_dependents": stopped_dependents,
        }
