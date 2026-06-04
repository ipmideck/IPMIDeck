import { useEffect, useState } from "react";
import { get, post } from "@/api/client";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Power, PowerOff, RotateCcw, RefreshCw, Zap, LayoutGrid, LineChart as LineChartIcon } from "lucide-react";
import { useBackendOnline } from "@/stores/connection-store";
import { usePowerStats, PowerLiveChart, formatKwh } from "@/modules/power/powerShared";

interface PowerControlsWidgetProps {
  serverId: string;
  /** "compact" = big number + stats + buttons. "chart" = inline stats + live chart + compact buttons. */
  view?: "compact" | "chart";
  /** Persist a view change via WidgetGrid → widget config. */
  onViewChange?: (view: "compact" | "chart") => void;
}

// Destructive actions — only meaningful while the host is running.
const DESTRUCTIVE = [
  { id: "soft", label: "Soft Off", icon: PowerOff },
  { id: "off", label: "Hard Off", icon: PowerOff },
  { id: "reset", label: "Reset", icon: RotateCcw },
  { id: "cycle", label: "Cycle", icon: RefreshCw },
] as const;

export function PowerControlsWidget({ serverId, view = "compact", onViewChange }: PowerControlsWidgetProps) {
  const [status, setStatus] = useState("unknown");
  const [loading, setLoading] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const online = useBackendOnline();
  const { live, unit, min, max, totalWh, sensorName, reset } = usePowerStats(serverId);

  useEffect(() => {
    if (!serverId) return;
    const poll = async () => {
      try {
        const data = await get<{ status: string }>(`/api/modules/power/${serverId}/status`);
        setStatus(data.status);
      } catch { /* ignore */ }
    };
    poll();
    const interval = setInterval(poll, 10000);
    return () => clearInterval(interval);
  }, [serverId]);

  const handleAction = async (action: string) => {
    if (action !== "on" && confirm !== action) {
      setConfirm(action);
      setTimeout(() => setConfirm(null), 3000);
      return;
    }
    setConfirm(null);
    setLoading(action);
    try {
      const res = await post<{ success: boolean; error?: string }>(`/api/modules/power/${serverId}/command`, { action });
      if (res.success) {
        toast.success(`Power ${action} executed`);
        setStatus(action === "on" || action === "reset" || action === "cycle" ? "on" : "off");
      } else {
        toast.error(res.error || "Command failed");
      }
    } catch (e: any) {
      toast.error(e.message || "Connection error");
    } finally {
      setLoading(null);
    }
  };

  if (!serverId) {
    return <div className="flex h-full items-center justify-center text-muted-foreground">—</div>;
  }

  const isOn = online && status === "on";
  const isOff = online && status === "off";
  const busy = loading !== null || !online;
  const isChart = view === "chart" && sensorName != null;

  // Reusable stats sub-block. Inline-3-values format works in both header (chart view)
  // and below the big number (compact view) without restyling.
  const StatBlock = ({ label, value }: { label: string; value: string }) => (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</span>
      <span className="font-mono text-[11px] text-foreground">{value}</span>
    </div>
  );

  return (
    <div
      className={cn(
        "flex h-full flex-col gap-1.5 transition-[filter,opacity]",
        !online && "opacity-50 grayscale"
      )}
    >
      {/* Row 1: status + chrome icons */}
      <div className="flex shrink-0 items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Power
            className={cn(
              "h-4 w-4",
              isOn ? "text-emerald-500" : isOff ? "text-red-500" : "text-muted-foreground"
            )}
          />
          <span
            className={cn(
              "font-mono text-sm font-semibold",
              isOn ? "text-emerald-500" : isOff ? "text-red-500" : "text-muted-foreground"
            )}
          >
            {!online ? "Unknown" : isOn ? "Online" : isOff ? "Offline" : "Unknown"}
          </span>
        </div>
        <div className="flex items-center gap-0.5">
          {sensorName != null && (
            <button
              type="button"
              onMouseDown={(e) => e.stopPropagation()}
              onClick={reset}
              title="Reset min/max/kWh counters"
              className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <RefreshCw className="h-3 w-3" />
            </button>
          )}
          {onViewChange && sensorName != null && (
            <button
              type="button"
              aria-label={isChart ? "Switch to compact view" : "Switch to chart view"}
              title={isChart ? "Hide chart" : "Show live chart"}
              onMouseDown={(e) => e.stopPropagation()}
              onClick={() => onViewChange(isChart ? "compact" : "chart")}
              className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              {isChart ? <LayoutGrid className="h-3 w-3" /> : <LineChartIcon className="h-3 w-3" />}
            </button>
          )}
        </div>
      </div>

      {/* Body — three branches: chart view (chart fills flex-1), compact view (big number),
          or fallback messaging. */}
      {!online ? (
        <div className="flex min-h-0 flex-1 items-center justify-center text-xs text-muted-foreground">
          Disconnected
        </div>
      ) : isChart && online ? (
        <>
          {/* Inline live + stats row, single line so the chart keeps maximum vertical space */}
          <div className="flex shrink-0 flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <div className="flex items-baseline gap-1">
              <Zap className="h-3.5 w-3.5 self-center text-violet-400" />
              <span className="font-mono text-lg font-bold tabular-nums">
                {live != null ? Math.round(live) : "—"}
              </span>
              <span className="text-[11px] text-muted-foreground">{unit}</span>
            </div>
            <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
              <span>Min <span className="font-mono text-foreground">{min != null ? `${Math.round(min)} ${unit}` : "—"}</span></span>
              <span>Max <span className="font-mono text-foreground">{max != null ? `${Math.round(max)} ${unit}` : "—"}</span></span>
              <span>Total <span className="font-mono text-foreground">{formatKwh(totalWh)}</span></span>
            </div>
          </div>
          {/* Recharts live chart — fills remaining vertical space */}
          <div className="min-h-0 flex-1">
            <PowerLiveChart serverId={serverId} sensorName={sensorName} />
          </div>
        </>
      ) : isOn && live != null ? (
        // Top-aligned, left-aligned column: wattage -> "Power draw" label ->
        // Min/Max/Total row. No vertical centering so the Power On button below
        // (in its own shrink-0 wrapper) never overlaps the stats at 2x2.
        <div className="flex min-h-0 flex-col gap-1">
          <div className="flex items-baseline gap-1">
            <Zap className="h-4 w-4 self-center text-violet-400" />
            <span className="font-mono text-3xl font-bold tabular-nums">{Math.round(live)}</span>
            <span className="text-sm text-muted-foreground">{unit}</span>
          </div>
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Power draw
          </span>
          {sensorName != null && (
            <div className="mt-1 flex items-center gap-4">
              <StatBlock label="Min" value={min != null ? `${Math.round(min)} ${unit}` : "—"} />
              <StatBlock label="Max" value={max != null ? `${Math.round(max)} ${unit}` : "—"} />
              <StatBlock label="Total" value={formatKwh(totalWh)} />
            </div>
          )}
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 items-center justify-center text-xs text-muted-foreground">
          {isOff ? "Server is powered off" : "No power reading"}
        </div>
      )}

      {/* Actions — single dense row in chart mode (so the chart keeps real estate),
          standard 2x2 grid in compact mode. */}
      <div className="shrink-0">
        {isChart ? (
          <div className="grid grid-cols-5 gap-1">
            <button
              onClick={() => handleAction("on")}
              disabled={busy || isOn}
              className={cn(
                "flex items-center justify-center gap-1 rounded-md border px-1.5 py-1.5 text-[10px] font-medium transition-colors",
                isOn
                  ? "cursor-not-allowed border-border text-muted-foreground/40"
                  : "border-emerald-500/40 bg-emerald-500/10 text-emerald-500 hover:bg-emerald-500/20",
                loading === "on" && "opacity-50"
              )}
            >
              <Power className="h-3 w-3" />
              <span className="hidden sm:inline">On</span>
            </button>
            {DESTRUCTIVE.map((a) => {
              const Icon = a.icon;
              const confirming = confirm === a.id;
              return (
                <button
                  key={a.id}
                  onClick={() => handleAction(a.id)}
                  disabled={busy || isOff}
                  className={cn(
                    "flex items-center justify-center gap-1 rounded-md border px-1.5 py-1.5 text-[10px] font-medium transition-colors",
                    confirming
                      ? "border-red-500 bg-red-500/20 text-red-400"
                      : "border-border text-muted-foreground hover:border-red-500/50 hover:text-red-400",
                    isOff && "cursor-not-allowed opacity-40 hover:border-border hover:text-muted-foreground",
                    loading === a.id && "opacity-50"
                  )}
                  title={a.label}
                >
                  <Icon className="h-3 w-3" />
                  <span className="truncate">{confirming ? "OK?" : a.label}</span>
                </button>
              );
            })}
          </div>
        ) : (
          <div className="mt-2 space-y-1.5">
            <button
              onClick={() => handleAction("on")}
              disabled={busy || isOn}
              className={cn(
                "flex w-full items-center justify-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[11px] font-medium transition-colors",
                isOn
                  ? "cursor-not-allowed border-border text-muted-foreground/40"
                  : "border-emerald-500/40 bg-emerald-500/10 text-emerald-500 hover:bg-emerald-500/20",
                loading === "on" && "opacity-50"
              )}
            >
              <Power className="h-3.5 w-3.5" />
              Power On
            </button>
            <div className="grid grid-cols-2 gap-1.5 border-t border-border pt-1.5">
              {DESTRUCTIVE.map((a) => {
                const Icon = a.icon;
                const confirming = confirm === a.id;
                return (
                  <button
                    key={a.id}
                    onClick={() => handleAction(a.id)}
                    disabled={busy || isOff}
                    className={cn(
                      "flex items-center justify-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[11px] font-medium transition-colors",
                      confirming
                        ? "border-red-500 bg-red-500/20 text-red-400"
                        : "border-border text-muted-foreground hover:border-red-500/50 hover:text-red-400",
                      isOff && "cursor-not-allowed opacity-40 hover:border-border hover:text-muted-foreground",
                      loading === a.id && "opacity-50"
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {confirming ? "Confirm?" : a.label}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
