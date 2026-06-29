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
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { SlidersHorizontal, Fan, LayoutGrid, LineChart as LineChartIcon } from "lucide-react";
import { CHART_TYPE_META, sensorNamesForChart, type ChartType } from "@/modules/sensors/sensorUtils";
import { SensorFilterMenu } from "@/modules/sensors/SensorFilterMenu";
import { cn } from "@/lib/utils";
import i18nInstance from "@/i18n";
import { intlLocale } from "@/i18n/languages";

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

// Inverse-to-speed thermal scale, routed through the semantic token system (D-01/D-04)
// instead of a raw red/orange/yellow/lime/emerald palette. Intent preserved:
//   stopped  -> danger  (alarm; pairs with the blink shape + "Fan Stopped" text)
//   slow     -> warning (running but barely moving air)
//   moderate -> warning, lighter tint (the mid step)
//   fast     -> success (healthy airflow)
//   max      -> cyan    (the project's cooling/fan motif — coldest/most air)
// `stroke` is a CSS var() reference (not a hardcoded hex) so the spinning <Fan> icon's
// inline style stays theme-correct in both light and dark.
function fanBand(rpm: number) {
  if (rpm <= 0) return { stroke: "var(--color-danger)", chip: "border-danger/40 bg-danger/10", label: "alarm" };
  if (rpm < 1500) return { stroke: "var(--color-warning)", chip: "border-warning/40 bg-warning/10", label: "low" };
  if (rpm < 3000) return { stroke: "var(--color-warning)", chip: "border-warning/25 bg-warning/5", label: "mid" };
  if (rpm < 6000) return { stroke: "var(--color-success)", chip: "border-success/30 bg-success/5", label: "high" };
  return { stroke: "var(--color-cyan)", chip: "border-cyan/30 bg-cyan/5", label: "max" };
}

// Calming spin: at 0 RPM no rotation; at high RPM still no faster than ~0.8s/rev.
// Even at 100% load the visual stays "alive but not frantic".
function fanSpinSeconds(rpm: number): number {
  const normalized = Math.max(0, Math.min(1, rpm / 10000));
  return Math.max(0.8, 5 - 4 * normalized);
}

// Best-fit {cols, rows} so all N cards fill the container with no scroll.
// Aspect target ~1.15 (slightly wider than tall -> readable RPM); penalize empty trailing cells.
function bestFanGrid(n: number, w: number, h: number, gap = 8): { cols: number; rows: number } {
  if (n <= 0) return { cols: 1, rows: 1 };
  if (w <= 0 || h <= 0) {
    // pre-measure fallback: count-only near-square
    const cols = Math.min(n, Math.ceil(Math.sqrt(n)));
    return { cols, rows: Math.ceil(n / cols) };
  }
  let best = { cols: 1, rows: n };
  let bestScore = Infinity;
  for (let cols = 1; cols <= n; cols++) {
    const rows = Math.ceil(n / cols);
    const cellW = (w - gap * (cols - 1)) / cols;
    const cellH = (h - gap * (rows - 1)) / rows;
    if (cellW <= 0 || cellH <= 0) continue;
    const aspect = cellW / cellH;
    const score = Math.abs(Math.log(aspect / 1.15)) + (cols * rows - n) * 0.5;
    if (score < bestScore) {
      bestScore = score;
      best = { cols, rows };
    }
  }
  return best;
}

function FanCard({ name, rpm, online, t }: { name: string; rpm: number | null; online: boolean; t: TFunction }) {
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
      <div
        className="flex min-h-0 min-w-0 flex-col items-center justify-center overflow-hidden rounded-lg border border-border bg-muted/20"
        style={{ containerType: "size", padding: "clamp(3px, 6cqmin, 10px)", gap: "clamp(2px, 4cqmin, 6px)" }}
      >
        <div className="flex items-center justify-center">
          <Fan
            className="text-muted-foreground"
            style={{ width: "clamp(16px, 42cqmin, 44px)", height: "clamp(16px, 42cqmin, 44px)" }}
          />
        </div>
        <div
          className="max-w-full truncate uppercase tracking-wider text-muted-foreground"
          style={{ fontSize: "clamp(7px, 13cqmin, 11px)" }}
          title={name}
        >
          {name}
        </div>
        <div
          className="font-mono font-semibold tabular-nums text-muted-foreground"
          style={{ fontSize: "clamp(9px, 17cqmin, 15px)" }}
        >
          —
        </div>
      </div>
    );
  }

  return (
    <div
      className={cn("flex min-h-0 min-w-0 flex-col items-center justify-center overflow-hidden rounded-lg border", band.chip)}
      style={{ containerType: "size", padding: "clamp(3px, 6cqmin, 10px)", gap: "clamp(2px, 4cqmin, 6px)" }}
    >
      <div className="flex items-center justify-center">
        <Fan
          className={cn(stopped && "animate-fan-alarm")}
          style={
            stopped
              ? { color: band.stroke, width: "clamp(16px, 42cqmin, 44px)", height: "clamp(16px, 42cqmin, 44px)" }
              : {
                  color: band.stroke,
                  animation: `fan-spin ${duration}s linear infinite`,
                  transformOrigin: "50% 50%",
                  width: "clamp(16px, 42cqmin, 44px)",
                  height: "clamp(16px, 42cqmin, 44px)",
                }
          }
        />
      </div>
      <div
        className="max-w-full truncate uppercase tracking-wider text-muted-foreground"
        style={{ fontSize: "clamp(7px, 13cqmin, 11px)" }}
        title={name}
      >
        {name}
      </div>
      <div
        className="font-mono font-semibold tabular-nums"
        style={{ fontSize: "clamp(9px, 17cqmin, 15px)" }}
      >
        {stopped ? t("widget.fanStopped") : `${rpm} RPM`}
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
  const { t, i18n } = useTranslation();
  // Active Intl locale for user-facing time labels (D-16). Pulling i18n from
  // useTranslation re-renders the chart on language change so the X-axis re-formats.
  const loc = intlLocale(i18n.resolvedLanguage);
  // SEPARATE state: live (WebSocket buffer) and historical (fetched) data never mix
  const [liveData, setLiveData] = useState<DataPoint[]>([]);
  const [historyData, setHistoryData] = useState<DataPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const range = useRangeStore((s) => s.range);
  const meta = CHART_TYPE_META[chartType];
  const lastUpdateRef = useRef(0);

  // Cards-view container measurement — drives a fit-to-widget {cols,rows} grid so all
  // fan cards are always visible with no vertical scroll. Deps keyed off view/chartType
  // so re-entering cards view re-observes the freshly mounted grid node.
  const cardsRef = useRef<HTMLDivElement | null>(null);
  const [cardsSize, setCardsSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = cardsRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const cr = entries[0]?.contentRect;
      if (cr) setCardsSize({ w: cr.width, h: cr.height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [view, chartType]);

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

      // Interval tick: effect deps don't include the language, so read the active locale
      // from the i18n singleton at tick-time to stay fresh after a language switch (D-16).
      const timeStr = new Date().toLocaleTimeString(intlLocale(i18nInstance.resolvedLanguage), { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });

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
    body = <div className="flex h-full items-center justify-center text-sm text-muted-foreground">{t("widget.unknownChartType")}</div>;
  } else if (allSensors.length === 0) {
    body = (
      <div className="flex h-full flex-col items-center justify-center text-center text-sm text-muted-foreground">
        <p>{t("widget.chartNoSensors", { type: chartType })}</p>
        <p className="mt-1 text-xs">{t("widget.chartWaitingReadings")}</p>
      </div>
    );
  } else if (visibleSensors.length === 0) {
    body = (
      <div className="flex h-full flex-col items-center justify-center text-center text-sm text-muted-foreground">
        <p>{t("widget.voltagesNoneSelectedTitle")}</p>
        <p className="mt-1 text-xs">{t("widget.chartNoneSelectedHint")}</p>
      </div>
    );
  } else if (chartType === "fan" && view === "cards") {
    // Animated cards view — one spinning fan per visible sensor. No history needed.
    // Fit-to-widget: compute {cols,rows} from the measured container so every card is
    // visible with NO scroll; each card scales to its cell via CSS container queries.
    const { cols, rows } = bestFanGrid(visibleSensors.length, cardsSize.w, cardsSize.h);
    body = (
      <div
        ref={cardsRef}
        className="grid h-full min-h-0 gap-2 pr-1 pt-1"
        style={{
          gridTemplateColumns: `repeat(${cols},minmax(0,1fr))`,
          gridTemplateRows: `repeat(${rows},minmax(0,1fr))`,
        }}
      >
        {visibleSensors.map((name) => {
          const r = readings?.[name];
          const v = r?.value;
          return (
            <FanCard
              key={name}
              name={name}
              rpm={typeof v === "number" ? v : null}
              online={online}
              t={t}
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
        <p>{t("widget.noDataForRange")}</p>
        <p className="mt-1 text-xs">{t("widget.noDataForRangeHint")}</p>
      </div>
    );
  } else if (range === "live" && liveData.length < 2) {
    body = (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        {t("widget.waitingForData")}
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
                : new Date(t).toLocaleTimeString(loc, { hour12: false, hour: "2-digit", minute: "2-digit" })
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
      <div className="flex items-center gap-1.5 rounded-md border border-danger/30 bg-card/95 px-2 py-0.5 text-[10px] font-medium text-danger shadow">
        <WifiOff className="h-3 w-3" />
        {t("power.disconnected")}
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
  const { t } = useTranslation();
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
        aria-label={view === "chart" ? t("widget.switchToFanCards") : t("widget.switchToChartView")}
        title={view === "chart" ? t("widget.showFansAsCards") : t("widget.showChart")}
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
        aria-label={t("widget.chooseSensors")}
        aria-haspopup="true"
        aria-expanded={filterOpen}
        onMouseDown={(e) => e.stopPropagation()}
        onClick={() => setFilterOpen((o) => !o)}
        className={cn(
          "flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] hover:bg-muted",
          hiddenSet.size > 0 ? "text-primary" : "text-muted-foreground"
        )}
        title={t("widget.chooseSensorsTitle")}
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
