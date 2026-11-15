-- Sensors a profile follows, as a JSON array of names (NULL: only source_sensor, as before).
ALTER TABLE fan_profiles ADD COLUMN source_sensors TEXT;

-- How several sensors are combined: 'max' (the hottest) or 'avg' (their mean).
ALTER TABLE fan_profiles ADD COLUMN sensor_mode TEXT NOT NULL DEFAULT 'max';
