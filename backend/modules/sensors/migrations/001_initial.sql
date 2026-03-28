CREATE TABLE IF NOT EXISTS sensor_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id TEXT NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    sensor_name TEXT NOT NULL,
    sensor_type TEXT NOT NULL,
    value REAL,
    unit TEXT,
    status TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_readings_server_time ON sensor_readings(server_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_readings_server_sensor_time ON sensor_readings(server_id, sensor_name, timestamp);
