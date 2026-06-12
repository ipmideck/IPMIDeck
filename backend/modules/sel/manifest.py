"""SEL module manifest."""

from pathlib import Path

from backend.core.modules import ModuleManifest
from backend.modules.sel.routes import router
from backend.modules.sel.tasks import sel_polling_loop

module = ModuleManifest(
    id="sel",
    name="Event Log",
    version="1.0.0",
    description="System Event Log viewer with filtering and export",
    category="diagnostics",
    icon="list",
    router=router,
    background_tasks=[sel_polling_loop],
    migrations_dir=Path(__file__).parent / "migrations",
    widgets=[
        {
            "id": "sel-recent",
            "name": "Recent Events",
            "description": "Latest SEL entries with severity badges",
            "sizes": ["2x2", "3x2", "4x2"],
            "default_size": "3x2",
            "category": "diagnostics",
        },
        {
            "id": "sel-count",
            "name": "Event Count",
            "description": "Total events by severity",
            "sizes": ["1x1"],
            "default_size": "1x1",
            "category": "diagnostics",
        },
    ],
)
