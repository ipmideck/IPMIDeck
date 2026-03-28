"""Sensor data API routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

router = APIRouter()


@router.get("/{server_id}/latest")
async def get_latest_sensors(server_id: str):
    """Get the most recent reading for each sensor on a server."""
    import backend.modules as ctx
    rows = await ctx.db.fetchall(
        """
        SELECT sensor_name, sensor_type, value, unit, status, MAX(timestamp) as timestamp
        FROM sensor_readings
        WHERE server_id = ?
        GROUP BY sensor_name
        ORDER BY sensor_type, sensor_name
        """,
        (server_id,),
    )
    return {"server_id": server_id, "sensors": rows}


@router.get("/{server_id}/history")
async def get_sensor_history(
    server_id: str,
    sensor_name: str = Query(...),
    range: str = Query("1h", regex="^(5m|1h|6h|24h|7d|30d)$"),
):
    """Get historical sensor data with automatic downsampling."""
    import backend.modules as ctx

    # Determine time offset and bucket size
    range_config = {
        "5m": ("5 minutes", None),        # raw data
        "1h": ("1 hour", 30),             # 30s buckets
        "6h": ("6 hours", 120),           # 2min buckets
        "24h": ("24 hours", 300),         # 5min buckets
        "7d": ("7 days", 1800),           # 30min buckets
        "30d": ("30 days", 7200),         # 2h buckets
    }

    offset, bucket_seconds = range_config[range]

    if bucket_seconds is None:
        # Raw data
        rows = await ctx.db.fetchall(
            """
            SELECT value, timestamp
            FROM sensor_readings
            WHERE server_id = ? AND sensor_name = ? AND timestamp > datetime('now', ?)
            ORDER BY timestamp
            """,
            (server_id, sensor_name, f"-{offset}"),
        )
    else:
        # Downsampled data
        rows = await ctx.db.fetchall(
            f"""
            SELECT
                AVG(value) as value,
                MIN(timestamp) as timestamp
            FROM sensor_readings
            WHERE server_id = ? AND sensor_name = ? AND timestamp > datetime('now', ?)
            GROUP BY CAST((strftime('%s', timestamp) / {bucket_seconds}) AS INTEGER)
            ORDER BY timestamp
            """,
            (server_id, sensor_name, f"-{offset}"),
        )

    return {"server_id": server_id, "sensor_name": sensor_name, "range": range, "data": rows}


@router.get("/{server_id}/types")
async def get_sensor_types(server_id: str):
    """List all sensor names and types for a server."""
    import backend.modules as ctx
    rows = await ctx.db.fetchall(
        """
        SELECT DISTINCT sensor_name, sensor_type, unit
        FROM sensor_readings
        WHERE server_id = ?
        ORDER BY sensor_type, sensor_name
        """,
        (server_id,),
    )
    return {"server_id": server_id, "sensor_types": rows}
