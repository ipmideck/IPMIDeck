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
            "description": "Power on/off/reset/cycle buttons with status",
            "sizes": ["2x2"],
            "default_size": "2x2",
            "category": "control",
        },
    ],
)
