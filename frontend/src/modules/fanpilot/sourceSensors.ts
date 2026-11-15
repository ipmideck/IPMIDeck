/**
 * The temperature sensors a fan profile follows, and how their readings are combined.
 *
 * Mirrors the backend: a profile follows 1 to MAX_SOURCE_SENSORS sensors combined as the
 * hottest ("max", the default) or their mean ("avg"). A profile saved before sensor lists
 * existed carries only `source_sensor`, which means that one sensor.
 */

export const MAX_SOURCE_SENSORS = 8;

export type SensorMode = "max" | "avg";

const DEFAULT_SOURCE_SENSOR = "CPU Temp";

interface ProfileSensorFields {
  source_sensor?: string | null;
  source_sensors?: unknown;
  sensor_mode?: unknown;
}

/** The sensors a profile follows; the single `source_sensor` when no list is stored. */
export function profileSensors(profile: ProfileSensorFields): string[] {
  const list = profile.source_sensors;
  if (Array.isArray(list) && list.length > 0 && list.every((n) => typeof n === "string")) {
    return [...list];
  }
  return [profile.source_sensor || DEFAULT_SOURCE_SENSOR];
}

export function profileSensorMode(profile: ProfileSensorFields): SensorMode {
  return profile.sensor_mode === "avg" ? "avg" : "max";
}

/**
 * The value the curve follows, computed the way the backend does. Null when any reading is
 * missing: the backend does not drop a silent sensor, it fails safe, so neither does this.
 */
export function combineTemps(
  values: (number | null | undefined)[],
  mode: SensorMode
): number | null {
  if (values.length === 0) return null;
  const nums: number[] = [];
  for (const v of values) {
    if (typeof v !== "number" || !Number.isFinite(v)) return null;
    nums.push(v);
  }
  if (mode === "avg") return nums.reduce((a, b) => a + b, 0) / nums.length;
  return Math.max(...nums);
}

/**
 * Tick or untick one sensor. A ticked sensor goes to the end of the list. The last sensor
 * cannot be unticked and no more than MAX_SOURCE_SENSORS can be ticked: both are no-ops.
 */
export function toggleSensor(selected: string[], name: string): string[] {
  if (selected.includes(name)) {
    if (selected.length <= 1) return selected;
    return selected.filter((n) => n !== name);
  }
  if (selected.length >= MAX_SOURCE_SENSORS) return selected;
  return [...selected, name];
}

interface SavableProfile {
  name: string;
  description: string;
  curve_points: unknown;
  hysteresis: number;
  safety_threshold: number;
  source_sensors: string[];
  sensor_mode: SensorMode;
}

/** PUT body for a profile. The backend derives `source_sensor` from the list's first name. */
export function profileSavePayload(profile: SavableProfile) {
  return {
    name: profile.name,
    description: profile.description,
    curve_points: profile.curve_points,
    hysteresis: profile.hysteresis,
    safety_threshold: profile.safety_threshold,
    source_sensors: profile.source_sensors,
    sensor_mode: profile.sensor_mode,
  };
}
