import { useSensorStore } from "@/stores/sensor-store";
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
import { useEffect, useState } from "react";

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
  const readings = useSensorStore((s) => s.readings[serverId]);
  const [history, setHistory] = useState<DataPoint[]>([]);
  const config = CHART_CONFIG[chartType];

  useEffect(() => {
    if (!readings) return;

    const now = new Date();
    const timeStr = now.toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });

    const point: DataPoint = { time: timeStr };
    for (const sensor of config.sensors) {
      const r = readings[sensor];
      point[sensor] = r?.value ?? null;
    }

    setHistory((prev) => {
      const updated = [...prev, point];
      // Keep last 60 data points (~5 min at 5s interval)
      return updated.slice(-60);
    });
  }, [readings, config.sensors]);

  if (history.length < 2) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Waiting for data...
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={history} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
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
