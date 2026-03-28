"""Sensors module manifest."""

from pathlib import Path

from backend.core.modules import ModuleManifest
from backend.modules.sensors.routes import router
from backend.modules.sensors.tasks import retention_cleanup_loop, sensor_polling_loop

module = ModuleManifest(
    id="sensors",
    name="Sensors",
    version="1.0.0",
    description="Real-time sensor monitoring — temperature, fan RPM, voltage, power",
    category="monitoring",
    icon="thermometer",
    router=router,
    background_tasks=[sensor_polling_loop, retention_cleanup_loop],
    migrations_dir=Path(__file__).parent / "migrations",
    widgets=[
        {
            "id": "sensors-metric",
            "name": "Sensor Metric",
            "description": "Single sensor value with sparkline",
            "sizes": ["1x1", "2x1"],
            "default_size": "1x1",
            "category": "monitoring",
        },
        {
            "id": "sensors-chart",
            "name": "Sensor Chart",
            "description": "Time-series chart for temperature, fan RPM, or power",
            "sizes": ["2x2", "3x2", "4x2", "6x2"],
            "default_size": "3x2",
            "category": "monitoring",
        },
        {
            "id": "sensors-voltages",
            "name": "Voltages",
            "description": "Voltage rails and PSU status overview",
            "sizes": ["1x2", "2x2"],
            "default_size": "1x2",
            "category": "monitoring",
        },
        {
            "id": "sensors-comparison",
            "name": "Sensor Comparison",
            "description": "Compare the same sensor across multiple servers",
            "sizes": ["3x2", "4x2", "6x2"],
            "default_size": "4x2",
            "category": "monitoring",
        },
    ],
)
