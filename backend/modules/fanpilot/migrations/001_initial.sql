CREATE TABLE IF NOT EXISTS fan_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    curve_points TEXT NOT NULL,
    interpolation TEXT DEFAULT 'linear',
    hysteresis REAL DEFAULT 3.0,
    safety_threshold REAL DEFAULT 85.0,
    source_sensor TEXT DEFAULT 'CPU Temp',
    is_preset INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Default profiles
INSERT OR IGNORE INTO fan_profiles (id, name, description, curve_points, is_preset) VALUES
(1, 'Silent', 'Prioritize low noise', '[{"temp":30,"speed":20},{"temp":50,"speed":30},{"temp":70,"speed":60},{"temp":85,"speed":100}]', 1),
(2, 'Balanced', 'Good compromise between noise and cooling', '[{"temp":30,"speed":30},{"temp":50,"speed":50},{"temp":70,"speed":80},{"temp":80,"speed":100}]', 1),
(3, 'Performance', 'Prioritize cooling', '[{"temp":30,"speed":50},{"temp":50,"speed":70},{"temp":70,"speed":90},{"temp":75,"speed":100}]', 1),
(4, 'Full Speed', 'Always 100%', '[{"temp":20,"speed":100},{"temp":100,"speed":100}]', 1);
