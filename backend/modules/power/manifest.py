"""Power module manifest."""

from pathlib import Path

from backend.core.modules import ModuleManifest
from backend.modules.power.routes import router

module = ModuleManifest(
    id="power",
    name="Power Control",
    version="1.0.0",
    description="Remote power management — on, off, reset, cycle",
    category="control",
    icon="power",
    router=router,
    migrations_dir=Path(__file__).parent / "migrations",
    widgets=[
        {
            "id": "power-status",
            "name": "Power Status",
            "description": "Server power state indicator",
            "sizes": ["1x1"],
            "default_size": "1x1",
            "category": "control",
        },
        {
            "id": "power-controls",
            "name": "Power Controls",
            "description": "Power state + draw + min/max/kWh + remote control buttons (toggle to a live chart view)",
            "sizes": ["2x2", "3x2"],
            "default_size": "2x2",
            "category": "control",
        },
        {
            "id": "power-stats",
            "name": "Power Stats",
            "description": "Live wattage with sparkline and session min/max/kWh — no control buttons",
            "sizes": ["2x2", "3x2"],
            "default_size": "2x2",
            "category": "monitoring",
        },
        {
            # 04-W2-06: Energy Cost — cost figure + cumulative kWh chart (Decision N).
            "id": "power-energy-cost",
            "name": "Energy Cost",
            "description": "Energy cost (currency) + cumulative kWh — 2x2 cost summary, 3x2 with chart",
            "sizes": ["2x2", "3x2"],
            "default_size": "2x2",
            "category": "monitoring",
        },
    ],
)
