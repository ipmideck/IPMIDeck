/**
 * Shared building blocks for the Power widgets (PowerControls + PowerStats):
 *   - usePowerStats: live value + session min/max/totalWh, with a stable kWh integrator
 *   - PowerSparkline: full-width SVG live trace, color-aware (violet by default)
 *   - pickPowerSensorName: vendor-agnostic "the power sensor we care about"
 *
 * Energy integration uses a fixed 3s frontend sample tick + trapezoidal rule, so kWh
 * stays accurate even when the backend repeats the same wattage across polls (idle
 * load). Counters reset on reset() or when the widget remounts.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { useSensorStore, type SensorReading } from "@/stores/sensor-store";
import { sensorNamesForType } from "@/modules/sensors/sensorUtils";

const SAMPLE_INTERVAL_MS = 3000;

/** Vendor-agnostic pick of "the" power sensor: prefer total/consumption, else first. */
export function pickPowerSensorName(
  readings: Record<string, SensorReading> | undefined
): string | null {
  if (!readings) return null;
  const names = sensorNamesForType(readings, "power");
  if (names.length === 0) return null;
  return names.find((n) => /consum|total|input/i.test(n)) ?? names[0];
}

export interface PowerStats {
  /** Latest sampled wattage (or null if unavailable). */
  live: number | null;
  /** Display unit — usually "W". */
  unit: string;
  /** Minimum value seen this session. */
  min: number | null;
  /** Maximum value seen this session. */
  max: number | null;
  /** Energy accumulated since session start, in watt-hours (divide by 1000 for kWh). */
  totalWh: number;
  /** Name of the power sensor this hook is tracking, or null if none. */
  sensorName: string | null;
  /** Reset min/max/totalWh to a clean session. */
  reset: () => void;
}

/**
 * Tracks the most-relevant power sensor for a server and accumulates session stats.
 * Safe to call from multiple widgets — each instance keeps its own session counters.
 */
export function usePowerStats(serverId: string): PowerStats {
  const readings = useSensorStore((s) => s.readings[serverId]);

  // Pick the power sensor whose name looks like "total/consumption/input" (R720
  // reports "Pwr Consumption"); else first by natural sort. Re-evaluated only when
  // the readings map for this server changes.
  const sensorName = useMemo(() => pickPowerSensorName(readings), [readings]);

  // Live value derived from the readings map — refreshes on every WS update.
  const live = useMemo<number | null>(() => {
    if (!sensorName || !readings) return null;
    const r = readings[sensorName];
    return typeof r?.value === "number" ? r.value : null;
  }, [readings, sensorName]);

  const [stats, setStats] = useState<{ min: number | null; max: number | null; totalWh: number }>({
    min: null,
    max: null,
    totalWh: 0,
  });

  // The fixed-tick integrator stores the LAST sampled value + timestamp so it can
  // trapezoid-integrate between samples even when the wattage plateaus (which it does
  // most of the time on an idle server).
  const lastRef = useRef<{ value: number; ts: number } | null>(null);

  useEffect(() => {
    // Restart the integrator any time the tracked sensor changes (e.g. server switch).
    lastRef.current = null;

    function tick() {
      // Read the FRESH store, not the closure's `readings` — the closure would be
      // stale relative to WS messages between re-renders.
      const r = useSensorStore.getState().readings[serverId];
      const name = pickPowerSensorName(r);
      if (!name || !r) return;
      const v = r[name]?.value;
      if (typeof v !== "number") return;

      const now = Date.now();
      const prev = lastRef.current;
      if (prev != null) {
        const dt = (now - prev.ts) / 1000; // seconds
        // Trapezoidal rule: average of two samples × dt (accurate even on plateaus).
        const avgW = (prev.value + v) / 2;
        const dWh = (avgW * dt) / 3600;
        setStats((s) => ({
          min: s.min === null ? v : Math.min(s.min, v),
          max: s.max === null ? v : Math.max(s.max, v),
          totalWh: s.totalWh + dWh,
        }));
      } else {
        // First sample of the session: seed min/max with it and reset totalWh.
        setStats({ min: v, max: v, totalWh: 0 });
      }
      lastRef.current = { value: v, ts: now };
    }

    tick(); // sample immediately so the first stats appear without a 3s wait
    const id = setInterval(tick, SAMPLE_INTERVAL_MS);
    return () => clearInterval(id);
  }, [serverId, sensorName]);

  const reset = useCallback(() => {
    lastRef.current = null;
    setStats({ min: null, max: null, totalWh: 0 });
  }, []);

  return {
    live,
    unit: "W",
    min: stats.min,
    max: stats.max,
    totalWh: stats.totalWh,
    sensorName,
    reset,
  };
}

interface ChartPoint {
  time: string;
  value: number | null;
}

/**
 * Full recharts live chart for the picked power sensor. Same look-and-feel as the
 * temperature/fan chart in SensorChart (CartesianGrid + axes + tooltip + ResponsiveContainer)
 * so the user gets a consistent reading experience across widgets.
 *
 * Maintains its own live buffer (60 points, ~3s tick) — independent of the global
 * sparkline buffer so the X-axis time labels stay coherent.
 */
export function PowerLiveChart({
  serverId,
  sensorName,
  color = "#a78bfa",
}: {
  serverId: string;
  sensorName: string | null;
  color?: string;
}) {
  const [data, setData] = useState<ChartPoint[]>([]);
  const lastUpdateRef = useRef(0);

  useEffect(() => {
    // Reset the buffer whenever we switch server or tracked sensor so the chart
    // doesn't mix data from two different sources.
    setData([]);
    if (!serverId || !sensorName) return;

    const tick = () => {
      const r = useSensorStore.getState().readings[serverId];
      if (!r) return;
      const now = Date.now();
      // Soft debounce so spurious re-renders don't append duplicate points.
      if (now - lastUpdateRef.current < 2000) return;
      lastUpdateRef.current = now;

      const v = r[sensorName]?.value;
      const timeStr = new Date().toLocaleTimeString("en-US", {
        hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit",
      });
      setData((prev) => [
        ...prev,
        { time: timeStr, value: typeof v === "number" ? v : null },
      ].slice(-60));
    };

    tick(); // seed the first point right away
    const id = setInterval(tick, 3000);
    return () => clearInterval(id);
  }, [serverId, sensorName]);

  if (!sensorName) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
        No power sensor
      </div>
    );
  }
  if (data.length < 2) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
        Waiting for data…
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="time"
          tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }}
          tickLine={false}
          axisLine={false}
          interval="preserveStartEnd"
        />
        <YAxis
          tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }}
          tickLine={false}
          axisLine={false}
          width={48}
        />
        <Tooltip
          contentStyle={{
            background: "var(--color-card)",
            border: "1px solid var(--color-border)",
            borderRadius: "6px",
            fontSize: "12px",
          }}
          labelStyle={{ color: "var(--color-muted-foreground)" }}
          formatter={(value) =>
            typeof value === "number" ? [`${Math.round(value)} W`, sensorName] : [String(value ?? "—"), sensorName]
          }
        />
        <Line
          type="monotone"
          dataKey="value"
          name={sensorName}
          stroke={color}
          strokeWidth={1.5}
          dot={false}
          activeDot={{ r: 3 }}
          connectNulls
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

/** Format kWh with sensible precision: 0.001 (Wh) → 9999.9 kWh range. */
export function formatKwh(totalWh: number): string {
  const kwh = totalWh / 1000;
  if (kwh < 0.001) return `${totalWh.toFixed(1)} Wh`;
  if (kwh < 1) return `${kwh.toFixed(3)} kWh`;
  if (kwh < 10) return `${kwh.toFixed(2)} kWh`;
  if (kwh < 100) return `${kwh.toFixed(1)} kWh`;
  return `${Math.round(kwh)} kWh`;
}
