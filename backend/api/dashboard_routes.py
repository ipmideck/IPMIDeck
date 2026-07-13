"""Dashboard routes — widget layout persistence and context server."""

from __future__ import annotations

import json

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class LayoutUpdate(BaseModel):
    layout: list[dict]


class ContextUpdate(BaseModel):
    server_id: str


@router.get("/layout")
async def get_layout():
    from backend.main import db
    row = await db.fetchone("SELECT layout FROM dashboard_layouts WHERE user_id = 0")
    if row:
        return {"layout": json.loads(row["layout"])}
    return {"layout": _default_layout()}


@router.put("/layout")
async def save_layout(body: LayoutUpdate):
    from backend.main import db
    await db.execute(
        "INSERT INTO dashboard_layouts (user_id, layout, updated_at) VALUES (0, ?, CURRENT_TIMESTAMP) "
        "ON CONFLICT(user_id) DO UPDATE SET layout = excluded.layout, updated_at = CURRENT_TIMESTAMP",
        (json.dumps(body.layout),),
    )
    await db.commit()
    return {"success": True}


@router.delete("/layout")
async def reset_layout():
    from backend.main import db
    await db.execute("DELETE FROM dashboard_layouts WHERE user_id = 0")
    await db.commit()
    return {"success": True, "layout": _default_layout()}


@router.get("/context")
async def get_context():
    from backend.main import db
    server_id = await db.get_config("context_server_id")
    return {"server_id": server_id}


@router.put("/context")
async def set_context(body: ContextUpdate):
    from backend.main import db
    await db.set_config("context_server_id", body.server_id)
    return {"success": True, "server_id": body.server_id}


@router.get("/widgets")
async def get_available_widgets():
    """Get all widget definitions from enabled modules (normalized for the catalog)."""
    from backend.main import module_loader
    out = []
    for w in module_loader.get_widgets_registry():
        size = str(w.get("default_size", "1x1"))
        try:
            dw, dh = (int(p) for p in size.lower().split("x", 1))
        except (ValueError, AttributeError):
            dw, dh = 1, 1
        out.append({
            **w,
            "widget_id": w["id"],
            "default_w": dw,
            "default_h": dh,
        })
    return {"widgets": out}


def _default_layout() -> list[dict]:
    """Default dashboard layout for first-time users (server-agnostic, demo-compatible).

    Mirrors the maintainer's reference layout on the 6-column grid: a top metric/status row,
    a wide temperature chart + fan tiles row, and a power-controls + voltages + energy-cost
    bottom row. No server_id binding — sensors resolve against the context server using demo
    sensor names ("CPU Temp" / "Inlet Temp" / "Exhaust Temp"). Per-widget view modes are seeded
    in config: fan chart in tile view ("view": "cards"), power controls in chart view
    ("view": "chart"); energy cost uses its cost-only summary view, driven by the 2x2 size.
    """
    return [
        # Row 0 (y=0, h=1) — five metric/status widgets across the 6-col top row
        {"i": "cpu-temp", "widget_id": "sensors-metric", "module_id": "sensors", "x": 0, "y": 0, "w": 1, "h": 1, "config": {"sensor": "CPU Temp"}},
        {"i": "inlet-temp", "widget_id": "sensors-metric", "module_id": "sensors", "x": 1, "y": 0, "w": 1, "h": 1, "config": {"sensor": "Inlet Temp"}},
        {"i": "fan-speed", "widget_id": "fanpilot-status", "module_id": "fanpilot", "x": 2, "y": 0, "w": 2, "h": 1},
        {"i": "exhaust-temp", "widget_id": "sensors-metric", "module_id": "sensors", "x": 4, "y": 0, "w": 1, "h": 1, "config": {"sensor": "Exhaust Temp"}},
        {"i": "power-status", "widget_id": "power-status", "module_id": "power", "x": 5, "y": 0, "w": 1, "h": 1},
        # Row 1 (y=1, h=2) — wide temperature chart + fan chart in tile/grid view
        {"i": "temp-chart", "widget_id": "sensors-chart", "module_id": "sensors", "x": 0, "y": 1, "w": 4, "h": 2, "config": {"type": "temperature"}},
        {"i": "fan-rpm", "widget_id": "sensors-chart", "module_id": "sensors", "x": 4, "y": 1, "w": 2, "h": 2, "config": {"type": "fan", "view": "cards", "hiddenSensors": []}},
        # Row 3 (y=3, h=2) — power controls (chart view) + voltages + energy cost (cost summary)
        {"i": "power-ctrl", "widget_id": "power-controls", "module_id": "power", "x": 0, "y": 3, "w": 3, "h": 2, "config": {"view": "chart"}},
        {"i": "voltages", "widget_id": "sensors-voltages", "module_id": "sensors", "x": 3, "y": 3, "w": 1, "h": 2},
        {"i": "energy-cost", "widget_id": "power-energy-cost", "module_id": "power", "x": 4, "y": 3, "w": 2, "h": 2},
    ]
