import { useSensorStore } from "@/stores/sensor-store";
import { useRangeStore } from "@/stores/range-store";
import { get } from "@/api/client";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { useEffect, useRef, useState } from "react";

interface SensorChartProps {
  serverId: string;
  chartType: "temperature" | "fan" | "power";
}

const CHART_CONFIG: Record<string, { sensors: string[]; colors: string[]; unit: string }> = {
  temperature: {
    sensors: ["CPU Temp", "Inlet Temp", "Exhaust Temp"],
    colors: ["#2563eb", "#10b981", "#8b5cf6"],
    unit: "°C",
  },
  fan: {
    sensors: ["Fan 1", "Fan 2", "Fan 3", "Fan 4"],
    colors: ["#f59e0b", "#f59e0b", "#f59e0b", "#f59e0b"],
    unit: "RPM",
  },
  power: {
    sensors: ["Power"],
    colors: ["#8b5cf6"],
    unit: "W",
  },
};

interface DataPoint {
  time: string;
  [key: string]: string | number | null;
}

export function SensorChart({ serverId, chartType }: SensorChartProps) {
  // SEPARATE state: live (WebSocket buffer) and historical (fetched) data never mix
  const [liveData, setLiveData] = useState<DataPoint[]>([]);
  const [historyData, setHistoryData] = useState<DataPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const range = useRangeStore((s) => s.range);
  const config = CHART_CONFIG[chartType];
  const lastUpdateRef = useRef(0);

  // Live buffer: poll store on interval and append clock-string points.
  // Gated to range === "live" so it stops growing in historical ranges.
  // This prevents infinite re-render loops (React error #185).
  useEffect(() => {
    if (range !== "live") return;
    if (!serverId || !config) return;
    const interval = setInterval(() => {
      const readings = useSensorStore.getState().readings[serverId];
      if (!readings) return;

      // Avoid duplicate points within the same second
      const now = Date.now();
      if (now - lastUpdateRef.current < 2000) return;
      lastUpdateRef.current = now;

      const timeStr = new Date().toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });

      const point: DataPoint = { time: timeStr };
      for (const sensor of config.sensors) {
        const r = readings[sensor];
        point[sensor] = r?.value ?? null;
      }

      setLiveData((prev) => [...prev, point].slice(-60));
    }, 3000);

    return () => clearInterval(interval);
  }, [serverId, chartType, config?.sensors, range]);

  // History fetch with stale-request guard + rolling refresh.
  // Separate state, reset on every transition; ISO-UTC normalization of SQLite timestamps.
  useEffect(() => {
    if (range === "live") {
      setHistoryData([]); // leave the history era when returning to Live
      return;
    }
    if (!serverId || !config) return;

    let cancelled = false; // stale-request / overlapping-interval guard
    setHistoryData([]); // reset on entering / changing a historical range
    setLoading(true);

    // Normalize SQLite "YYYY-MM-DD HH:MM:SS" -> ISO UTC for reliable new Date()
    const toIso = (t: string) =>
      /[zZ]|[+-]\d\d:?\d\d$/.test(t) ? t : t.replace(" ", "T") + "Z";

    async function loadHistory() {
      const results = await Promise.all(
        config.sensors.map((name) =>
          get<{ data: { value: number; timestamp: string }[] }>(
            `/api/modules/sensors/${serverId}/history?sensor_name=${encodeURIComponent(name)}&range=${range}`
          )
            .then((r) => ({ name, data: r.data }))
            .catch(() => ({ name, data: [] as { value: number; timestamp: string }[] }))
        )
      );
      if (cancelled) return; // discard a fetch that resolved after deps changed
      const byTs = new Map<string, DataPoint>();
      for (const { name, data } of results) {
        for (const pt of data) {
          const iso = toIso(pt.timestamp);
          const row = byTs.get(iso) ?? { time: iso };
          row[name] = pt.value;
          byTs.set(iso, row);
        }
      }
      const merged = [...byTs.values()].sort((a, b) =>
        String(a.time).localeCompare(String(b.time))
      );
      if (cancelled) return;
      setHistoryData(merged);
      setLoading(false);
    }

    loadHistory();
    const id = setInterval(loadHistory, 15000); // rolling refresh (silent)
    return () => {
      cancelled = true; // mark in-flight fetches stale BEFORE clearing the interval
      clearInterval(id); // clear interval before a new effect run starts a new one
    };
  }, [serverId, chartType, range]);

  const chartData = range === "live" ? liveData : historyData;

  if (!serverId) {
    return <div className="flex h-full items-center justify-center text-muted-foreground">—</div>;
  }

  if (!config) {
    return <div className="flex h-full items-center justify-center text-sm text-muted-foreground">Unknown chart type</div>;
  }

  // History loading spinner (do NOT collapse widget height)
  if (range !== "live" && loading && historyData.length === 0) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
      </div>
    );
  }

  // History empty state (range has no accumulated data)
  if (range !== "live" && !loading && historyData.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-center text-sm text-muted-foreground">
        <p>No data for this range</p>
        <p className="mt-1 text-xs">History accumulates over time — check back later.</p>
      </div>
    );
  }

  // Live "waiting" state only applies to the live buffer
  if (range === "live" && liveData.length < 2) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Waiting for data...
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
        <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="time"
          tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }}
          tickLine={false}
          axisLine={false}
          interval="preserveStartEnd"
          tickFormatter={(t: string) =>
            range === "live"
              ? t
              : new Date(t).toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit" })
          }
        />
        <YAxis
          tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }}
          tickLine={false}
          axisLine={false}
          width={40}
        />
        <Tooltip
          contentStyle={{
            background: "var(--color-card)",
            border: "1px solid var(--color-border)",
            borderRadius: "6px",
            fontSize: "12px",
          }}
          labelStyle={{ color: "var(--color-muted-foreground)" }}
        />
        <Legend
          wrapperStyle={{ fontSize: "11px", paddingTop: "4px" }}
          iconType="square"
          iconSize={8}
        />
        {config.sensors.map((sensor, i) => (
          <Line
            key={sensor}
            type="monotone"
            dataKey={sensor}
            stroke={config.colors[i % config.colors.length]}
            strokeWidth={1.5}
            dot={false}
            activeDot={{ r: 3 }}
            connectNulls
            opacity={i === 0 ? 1 : 0.6}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
