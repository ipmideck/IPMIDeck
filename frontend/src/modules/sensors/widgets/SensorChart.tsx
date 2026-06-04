import { useSensorStore } from "@/stores/sensor-store";
import { useRangeStore } from "@/stores/range-store";
import { useBackendOnline } from "@/stores/connection-store";
import { get } from "@/api/client";
import { WifiOff } from "lucide-react";
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
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { SlidersHorizontal, Fan, LayoutGrid, LineChart as LineChartIcon } from "lucide-react";
import { CHART_TYPE_META, sensorNamesForChart, type ChartType } from "@/modules/sensors/sensorUtils";
import { SensorFilterMenu } from "@/modules/sensors/SensorFilterMenu";
import { cn } from "@/lib/utils";

export type SensorChartView = "chart" | "cards";

interface SensorChartProps {
  serverId: string;
  chartType: ChartType;
  /** Sensor names hidden from this chart (persisted per widget). Defaults to none (show all). */
  hiddenSensors?: string[];
  /** Persist the new hidden-set into the widget config. Wired by WidgetGrid via onConfigChange. */
  onHiddenChange?: (hidden: string[]) => void;
  /** View mode (chart line graph vs animated fan cards). Only the "fan" chartType actually
   *  honours "cards" — other chart types always render the chart. */
  view?: SensorChartView;
  /** Persist a view change. Wired by WidgetGrid via onConfigChange. */
  onViewChange?: (view: SensorChartView) => void;
}

/* ------------------------------------------------------------------ */
/*  Fan visual mapping (cards view)                                    */
/* ------------------------------------------------------------------ */

// Inverse-to-speed color: stopped = red, faster = greener. Used for both icon stroke
// color and the card border/background tint.
function fanBand(rpm: number) {
  if (rpm <= 0) return { stroke: "#ef4444", chip: "border-red-500/40 bg-red-500/10", label: "alarm" };
  if (rpm < 1500) return { stroke: "#f97316", chip: "border-orange-500/30 bg-orange-500/5", label: "low" };
  if (rpm < 3000) return { stroke: "#eab308", chip: "border-yellow-500/30 bg-yellow-500/5", label: "mid" };
  if (rpm < 6000) return { stroke: "#84cc16", chip: "border-lime-500/30 bg-lime-500/5", label: "high" };
  return { stroke: "#22c55e", chip: "border-emerald-500/30 bg-emerald-500/5", label: "max" };
}

// Calming spin: at 0 RPM no rotation; at high RPM still no faster than ~0.8s/rev.
// Even at 100% load the visual stays "alive but not frantic".
function fanSpinSeconds(rpm: number): number {
  const normalized = Math.max(0, Math.min(1, rpm / 10000));
  return Math.max(0.8, 5 - 4 * normalized);
}

function FanCard({ name, rpm, online }: { name: string; rpm: number | null; online: boolean }) {
  const stopped = rpm == null || rpm <= 0;
  const band = fanBand(rpm ?? 0);
  const duration = stopped ? 0 : fanSpinSeconds(rpm ?? 0);

  // When the backend is offline we DON'T know the real RPM — showing a still-spinning
  // fan would be a lie, and showing the "STOPPED" red alarm would be a different lie
  // (we don't know it's stopped, it just hasn't been reported recently). Render a
  // neutral, dimmed card with "—" so the user understands the state is unknown.
  if (!online) {
    // Parent SensorChart wrapper already applies opacity-50 grayscale — don't add a
    // second opacity here or the two compound multiplicatively to ~30% effective.
    return (
      <div className="flex flex-col items-center justify-center gap-1.5 rounded-lg border border-border bg-muted/20 p-2.5">
        <div className="flex h-12 w-12 items-center justify-center">
          <Fan className="h-10 w-10 text-muted-foreground" />
        </div>
        <div className="truncate text-[10px] uppercase tracking-wider text-muted-foreground" title={name}>
          {name}
        </div>
        <div className="font-mono text-sm font-semibold tabular-nums text-muted-foreground">—</div>
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col items-center justify-center gap-1.5 rounded-lg border p-2.5", band.chip)}>
      <div className="flex h-12 w-12 items-center justify-center">
        <Fan
          className={cn("h-10 w-10", stopped && "animate-fan-alarm")}
          style={
            stopped
              ? { color: band.stroke }
              : { color: band.stroke, animation: `fan-spin ${duration}s linear infinite`, transformOrigin: "50% 50%" }
          }
        />
      </div>
      <div className="truncate text-[10px] uppercase tracking-wider text-muted-foreground" title={name}>
        {name}
      </div>
      <div className="font-mono text-sm font-semibold tabular-nums">
        {stopped ? "STOPPED" : `${rpm} RPM`}
      </div>
    </div>
  );
}

interface DataPoint {
  time: string;
  [key: string]: string | number | null;
}

export function SensorChart({
  serverId,
  chartType,
  hiddenSensors,
  onHiddenChange,
  view = "chart",
  onViewChange,
}: SensorChartProps) {
  // SEPARATE state: live (WebSocket buffer) and historical (fetched) data never mix
  const [liveData, setLiveData] = useState<DataPoint[]>([]);
  const [historyData, setHistoryData] = useState<DataPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const range = useRangeStore((s) => s.range);
  const meta = CHART_TYPE_META[chartType];
  const lastUpdateRef = useRef(0);

  // Subscribe to the readings MAP for this server (stable ref per server — Zustand v5
  // returns the same object reference unless it changes, so this won't trip React #185).
  const readings = useSensorStore((s) => s.readings[serverId]);
  // Backend connectivity — drives stop-on-offline for fan animations and the chart overlay.
  const online = useBackendOnline();

  // ALL sensors whose backend `type` matches (the full set this chart could draw). The DATA
  // layer (live buffer + history fetch) always collects these so toggling visibility never
  // loses buffered/historical data — the hidden filter only affects which LINES are drawn.
  const allSensors = useMemo(
    () => sensorNamesForChart(readings, chartType),
    [readings, chartType]
  );
  const sensorsKey = allSensors.join(" "); // stable string dep for effects (avoids array identity churn)

  const hiddenSet = useMemo(() => new Set(hiddenSensors ?? []), [hiddenSensors]);
  // Visible = matching sensors minus the user-hidden ones. Colors are keyed off allSensors
  // index so hiding one series never recolors the others.
  const visibleSensors = allSensors.filter((s) => !hiddenSet.has(s));
  const colorFor = (name: string) => {
    const i = allSensors.indexOf(name);
    return meta.basePalette[(i < 0 ? 0 : i) % meta.basePalette.length];
  };

  // Live buffer: poll store on interval and append clock-string points (collects ALL matching
  // sensors; render-time filter decides what is shown). Gated to range === "live".
  useEffect(() => {
    if (range !== "live") return;
    if (!serverId) return;
    const interval = setInterval(() => {
      const r = useSensorStore.getState().readings[serverId];
      if (!r) return;

      const now = Date.now();
      if (now - lastUpdateRef.current < 2000) return;
      lastUpdateRef.current = now;

      const timeStr = new Date().toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });

      const point: DataPoint = { time: timeStr };
      for (const name of sensorNamesForChart(r, chartType)) {
        point[name] = r[name]?.value ?? null;
      }

      setLiveData((prev) => [...prev, point].slice(-60));
    }, 3000);

    return () => clearInterval(interval);
  }, [serverId, chartType, range]);

  // History fetch with stale-request guard + rolling refresh (fetches ALL matching sensors).
  useEffect(() => {
    if (range === "live") {
      setHistoryData([]);
      return;
    }
    if (!serverId) return;

    const names = sensorsKey ? sensorsKey.split(" ") : [];
    if (names.length === 0) {
      setHistoryData([]);
      setLoading(false);
      return;
    }

    let cancelled = false;
    setHistoryData([]);
    setLoading(true);

    const toIso = (t: string) =>
      /[zZ]|[+-]\d\d:?\d\d$/.test(t) ? t : t.replace(" ", "T") + "Z";

    async function loadHistory() {
      const results = await Promise.all(
        names.map((name) =>
          get<{ data: { value: number; timestamp: string }[] }>(
            `/api/modules/sensors/${serverId}/history?sensor_name=${encodeURIComponent(name)}&range=${range}`
          )
            .then((r) => ({ name, data: r.data }))
            .catch(() => ({ name, data: [] as { value: number; timestamp: string }[] }))
        )
      );
      if (cancelled) return;
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
    const id = setInterval(loadHistory, 15000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [serverId, range, sensorsKey]);

  const chartData = range === "live" ? liveData : historyData;

  // Header chrome (view toggle + sensor filter) now lives in the widget card
  // HEADER via SensorChartHeaderActions (see registry) — no longer rendered
  // over the body as a floating top-right cluster.

  // --- Body: one of several states; the disconnected overlay still renders below ---
  let body: React.ReactNode;

  if (!serverId) {
    body = <div className="flex h-full items-center justify-center text-muted-foreground">—</div>;
  } else if (!meta) {
    body = <div className="flex h-full items-center justify-center text-sm text-muted-foreground">Unknown chart type</div>;
  } else if (allSensors.length === 0) {
    body = (
      <div className="flex h-full flex-col items-center justify-center text-center text-sm text-muted-foreground">
        <p>No {chartType} sensors</p>
        <p className="mt-1 text-xs">Waiting for readings or this server reports none.</p>
      </div>
    );
  } else if (visibleSensors.length === 0) {
    body = (
      <div className="flex h-full flex-col items-center justify-center text-center text-sm text-muted-foreground">
        <p>No sensors selected</p>
        <p className="mt-1 text-xs">Use the filter (top-right) to choose which to show.</p>
      </div>
    );
  } else if (chartType === "fan" && view === "cards") {
    // Animated cards view — one spinning fan per visible sensor. No history needed.
    body = (
      <div className="grid h-full content-start gap-2 overflow-y-auto pr-1 pt-1 [grid-template-columns:repeat(auto-fill,minmax(110px,1fr))]">
        {visibleSensors.map((name) => {
          const r = readings?.[name];
          const v = r?.value;
          return (
            <FanCard
              key={name}
              name={name}
              rpm={typeof v === "number" ? v : null}
              online={online}
            />
          );
        })}
      </div>
    );
  } else if (range !== "live" && loading && historyData.length === 0) {
    body = (
      <div className="flex h-full items-center justify-center">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
      </div>
    );
  } else if (range !== "live" && !loading && historyData.length === 0) {
    body = (
      <div className="flex h-full flex-col items-center justify-center text-center text-sm text-muted-foreground">
        <p>No data for this range</p>
        <p className="mt-1 text-xs">History accumulates over time — check back later.</p>
      </div>
    );
  } else if (range === "live" && liveData.length < 2) {
    body = (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Waiting for data...
      </div>
    );
  } else {
    body = (
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
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
          />
          <Legend
            wrapperStyle={{ fontSize: "11px", paddingTop: "4px" }}
            iconType="square"
            iconSize={8}
          />
          {visibleSensors.map((sensor) => (
            <Line
              key={sensor}
              type="monotone"
              dataKey={sensor}
              stroke={colorFor(sensor)}
              strokeWidth={1.5}
              dot={false}
              activeDot={{ r: 3 }}
              connectNulls
              opacity={allSensors.indexOf(sensor) === 0 ? 1 : 0.7}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    );
  }

  // Disconnected marker — anchored to the BOTTOM-LEFT corner so it doesn't fight
  // with centered empty-state text ("No X sensors / Waiting for readings…") or with
  // the top-right control icons. Small, unobtrusive, always reachable.
  const disconnectedOverlay = !online ? (
    <div className="pointer-events-none absolute bottom-2 left-2 z-10">
      <div className="flex items-center gap-1.5 rounded-md border border-red-500/30 bg-card/95 px-2 py-0.5 text-[10px] font-medium text-red-500 shadow">
        <WifiOff className="h-3 w-3" />
        Disconnected
      </div>
    </div>
  ) : null;

  return (
    <div className="relative h-full">
      <div className={cn("h-full", !online && "opacity-50 grayscale transition-[filter,opacity]")}>
        {body}
      </div>
      {disconnectedOverlay}
    </div>
  );
}

/**
 * Header-action chrome for the SensorChart widget — rendered by WidgetGrid in
 * the widget card title bar (not inside the body). Owns the filter-menu open
 * state and re-implements the toggleSensor/setAll callbacks on top of the same
 * onHiddenChange / hiddenSensors / view props that drive the body, so the two
 * stay in sync without internal state sharing.
 *
 * All buttons stopPropagation on mousedown so dragging the card header isn't
 * hijacked by header-action clicks.
 */
export function SensorChartHeaderActions({
  serverId,
  chartType,
  hiddenSensors,
  onHiddenChange,
  view = "chart",
  onViewChange,
}: SensorChartProps) {
  const readings = useSensorStore((s) => s.readings[serverId]);
  const allSensors = useMemo(
    () => sensorNamesForChart(readings, chartType),
    [readings, chartType]
  );
  const hiddenSet = useMemo(() => new Set(hiddenSensors ?? []), [hiddenSensors]);
  const visibleSensors = allSensors.filter((s) => !hiddenSet.has(s));
  const [filterOpen, setFilterOpen] = useState(false);
  const filterRef = useRef<HTMLButtonElement>(null);

  const toggleSensor = useCallback(
    (name: string) => {
      if (!onHiddenChange) return;
      const next = new Set(hiddenSensors ?? []);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      onHiddenChange([...next]);
    },
    [hiddenSensors, onHiddenChange]
  );

  const setAll = useCallback(
    (show: boolean) => {
      if (!onHiddenChange) return;
      onHiddenChange(show ? [] : [...allSensors]);
    },
    [allSensors, onHiddenChange]
  );

  const viewToggle =
    chartType === "fan" && onViewChange ? (
      <button
        type="button"
        aria-label={view === "chart" ? "Switch to fan cards view" : "Switch to chart view"}
        title={view === "chart" ? "Show fans as cards" : "Show chart"}
        onMouseDown={(e) => e.stopPropagation()}
        onClick={() => onViewChange(view === "chart" ? "cards" : "chart")}
        className="flex items-center rounded px-1.5 py-0.5 text-[10px] text-muted-foreground hover:bg-muted"
      >
        {view === "chart" ? <LayoutGrid className="h-3 w-3" /> : <LineChartIcon className="h-3 w-3" />}
      </button>
    ) : null;

  const filterButton =
    onHiddenChange && allSensors.length > 0 ? (
      <button
        ref={filterRef}
        type="button"
        aria-label="Choose sensors"
        aria-haspopup="true"
        aria-expanded={filterOpen}
        onMouseDown={(e) => e.stopPropagation()}
        onClick={() => setFilterOpen((o) => !o)}
        className={cn(
          "flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] hover:bg-muted",
          hiddenSet.size > 0 ? "text-primary" : "text-muted-foreground"
        )}
        title="Choose which sensors to show"
      >
        <SlidersHorizontal className="h-3 w-3" />
        {hiddenSet.size > 0 && <span>{visibleSensors.length}/{allSensors.length}</span>}
      </button>
    ) : null;

  if (!viewToggle && !filterButton) return null;

  return (
    <>
      {viewToggle}
      {filterButton}
      {filterOpen && (
        <SensorFilterMenu
          anchorRef={filterRef}
          allSensors={allSensors}
          hiddenSet={hiddenSet}
          readings={readings}
          onToggle={toggleSensor}
          onAll={setAll}
          onClose={() => setFilterOpen(false)}
        />
      )}
    </>
  );
}
