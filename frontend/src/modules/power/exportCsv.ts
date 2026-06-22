import type { ChartRange } from "@/stores/range-store";

/**
 * 04-W6-03: trigger a browser download of a sensor's history as CSV.
 *
 * Hits GET /api/system/history-csv with the current useRangeStore range value
 * ("live" | "1h" | "24h" | "7d") — already wire-compatible with the backend
 * _RANGE_OFFSETS map (server IDs are strings end-to-end, Decision C). Uses an
 * anchor click rather than the @/api/client wrapper because the response body is
 * a streamed text/csv attachment, not JSON.
 *
 * No-op when sensorName is null (the widget hasn't resolved a power sensor yet).
 */
export function exportSensorCsv(
  serverId: string,
  sensorName: string | null,
  range: ChartRange
): void {
  if (!serverId || !sensorName) return;
  const url =
    `/api/system/history-csv?server_id=${encodeURIComponent(serverId)}` +
    `&sensor_name=${encodeURIComponent(sensorName)}` +
    `&range=${encodeURIComponent(range)}`;
  const a = document.createElement("a");
  a.href = url;
  a.download = `ipmideck-${sensorName.replace(/[ /]/g, "_")}-${range}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
}
