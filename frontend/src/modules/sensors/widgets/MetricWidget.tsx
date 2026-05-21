import { useSensorStore } from "@/stores/sensor-store";
import { cn } from "@/lib/utils";

// Stable empty-array reference for the sparkline selector. Returning a fresh `[]`
// on every render trips Zustand v5's Object.is equality check, triggering an
// infinite re-render loop (React #185). A single module-level constant keeps the
// reference stable across renders.
const EMPTY: number[] = [];

interface MetricWidgetProps {
  serverId: string;
  sensorName: string;
  label?: string;
}

function Sparkline({ data, color }: { data: number[]; color: string }) {
  if (data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const w = 80;
  const h = 24;
  const points = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * w;
      const y = h - ((v - min) / range) * h;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <svg width={w} height={h} className="mt-1 opacity-60">
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function MetricWidget({ serverId, sensorName, label }: MetricWidgetProps) {
  const reading = useSensorStore((s) => s.readings[serverId]?.[sensorName]);
  const sparkline = useSensorStore((s) => s.sparklines[serverId]?.[sensorName] ?? EMPTY);

  if (!serverId) {
    return <div className="flex h-full items-center justify-center text-muted-foreground">—</div>;
  }

  try {
    const value = reading?.value;
    const unit = reading?.unit || "";
    const status = reading?.status || "unknown";

    const badgeBg =
      status === "ok" ? "bg-emerald-500/10 text-emerald-500" :
      status === "warning" ? "bg-yellow-500/10 text-yellow-500" :
      status === "critical" ? "bg-red-500/10 text-red-500" : "bg-muted text-muted-foreground";

    const chartColor =
      unit === "C" ? "#2563eb" :
      unit === "RPM" ? "#f59e0b" :
      unit === "W" ? "#8b5cf6" :
      unit === "V" ? "#10b981" : "#a1a1aa";

    return (
      <div className="flex h-full flex-col justify-center">
        <div className="font-mono text-2xl font-semibold leading-none tracking-tight">
          {value !== null && value !== undefined ? (
            <>
              {typeof value === "number" ? (Number.isInteger(value) ? value : value.toFixed(1)) : value}
              <span className="ml-0.5 text-sm font-normal text-muted-foreground">{unit}</span>
            </>
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
        </div>
        <div className="mt-1 flex items-center gap-2">
          <span className={cn("inline-flex rounded-full px-1.5 py-0.5 text-[10px] font-semibold", badgeBg)}>
            {status === "ok" ? "Normal" : status}
          </span>
        </div>
        <Sparkline data={Array.isArray(sparkline) ? sparkline : []} color={chartColor} />
      </div>
    );
  } catch {
    return <div className="flex h-full items-center justify-center text-muted-foreground">—</div>;
  }
}
