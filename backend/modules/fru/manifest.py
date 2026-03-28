"""FRU module manifest."""

from pathlib import Path

from backend.core.modules import ModuleManifest
from backend.modules.fru.routes import router

module = ModuleManifest(
    id="fru",
    name="Hardware",
    version="1.0.0",
    description="Hardware inventory — serial numbers, part numbers, manufacturer info",
    category="diagnostics",
    icon="cpu",
    router=router,
    migrations_dir=Path(__file__).parent / "migrations",
    widgets=[
        {
            "id": "fru-summary",
            "name": "Hardware Summary",
            "description": "Server model, serial number, manufacturer",
            "sizes": ["2x1", "2x2"],
            "default_size": "2x1",
            "category": "diagnostics",
        },
    ],
)
