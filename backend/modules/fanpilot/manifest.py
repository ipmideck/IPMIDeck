"""FanPilot module manifest."""

from pathlib import Path

from backend.core.modules import ModuleManifest
from backend.modules.fanpilot.routes import router
from backend.modules.fanpilot.tasks import fanpilot_loop, fanpilot_shutdown

module = ModuleManifest(
    id="fanpilot",
    name="FanPilot",
    version="1.0.0",
    description="Intelligent fan curve control with drag-and-drop editor",
    category="cooling",
    icon="fan",
    dependencies=["sensors"],
    router=router,
    background_tasks=[fanpilot_loop],
    on_shutdown=fanpilot_shutdown,
    migrations_dir=Path(__file__).parent / "migrations",
    widgets=[
        {
            "id": "fanpilot-status",
            "name": "FanPilot Status",
            "description": "Current mode, profile, and fan speed",
            "sizes": ["1x1", "2x1"],
            "default_size": "2x1",
            "category": "cooling",
        },
        {
            "id": "fanpilot-curve",
            "name": "Fan Curve",
            "description": "Live fan curve with current temperature indicator",
            "sizes": ["2x2", "3x2", "6x3"],
            "default_size": "2x2",
            "category": "cooling",
        },
        {
            "id": "fanpilot-actions",
            "name": "FanPilot Quick Actions",
            "description": "Profile switcher and mode toggle",
            "sizes": ["2x2"],
            "default_size": "2x2",
            "category": "cooling",
        },
    ],
)
