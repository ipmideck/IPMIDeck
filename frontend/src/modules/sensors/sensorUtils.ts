import type { SensorReading } from "@/stores/sensor-store";

/** Map a chart's high-level category to the backend sensor `type` it should render. */
export type ChartType = "temperature" | "fan" | "power";

export const CHART_TYPE_META: Record<ChartType, { unit: string; basePalette: string[] }> = {
  // Cool blues / teals for temperature
  temperature: { unit: "°C", basePalette: ["#2563eb", "#10b981", "#8b5cf6", "#06b6d4", "#0ea5e9", "#14b8a6", "#6366f1", "#f43f5e"] },
  // Amber family for fans (RPM)
  fan: { unit: "RPM", basePalette: ["#f59e0b", "#f97316", "#eab308", "#fb923c", "#d97706", "#facc15", "#ea580c", "#ca8a04"] },
  // Violet family for power (W)
  power: { unit: "W", basePalette: ["#8b5cf6", "#a855f7", "#7c3aed", "#c084fc", "#9333ea"] },
};

/**
 * Return the sensor NAMES (real, vendor-specific) whose backend `type` matches the chart type,
 * sorted by natural name order so e.g. Fan1..Fan6 line up predictably and colors are stable.
 *
 * Driven by `type`, never by hardcoded demo names — handles N fans / N temps on any BMC.
 */
export function sensorNamesForChart(
  readings: Record<string, SensorReading> | undefined,
  chartType: ChartType
): string[] {
  if (!readings) return [];
  return Object.entries(readings)
    .filter(([, r]) => r?.type === chartType)
    .map(([name]) => name)
    .sort(naturalCompare);
}

/** Names for a given backend type (used by VoltagesWidget for voltage/current). */
export function sensorNamesForType(
  readings: Record<string, SensorReading> | undefined,
  type: string
): string[] {
  if (!readings) return [];
  return Object.entries(readings)
    .filter(([, r]) => r?.type === type)
    .map(([name]) => name)
    .sort(naturalCompare);
}

/** Natural sort so "Fan2" < "Fan10" and "Temp" < "Temp (2)". */
export function naturalCompare(a: string, b: string): number {
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
}
