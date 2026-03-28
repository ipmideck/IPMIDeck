CREATE TABLE IF NOT EXISTS sel_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id TEXT NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    event_id TEXT,
    timestamp DATETIME,
    sensor_name TEXT,
    event_type TEXT,
    description TEXT,
    severity TEXT,
    raw_data TEXT,
    fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sel_server_time ON sel_cache(server_id, timestamp);
