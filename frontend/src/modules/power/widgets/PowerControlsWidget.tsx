import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { post } from "@/api/client";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Power, PowerOff, RotateCcw, RefreshCw, Zap, Settings, LayoutGrid, LineChart as LineChartIcon } from "lucide-react";
import { useBackendOnline } from "@/stores/connection-store";
import { useServerStore } from "@/stores/server-store";
import { usePowerStore } from "@/stores/power-store";
import { useCurrencyStore } from "@/stores/currency-store";
import { formatCurrency } from "@/lib/currency";
import { usePowerStats, PowerLiveChart, formatKwh } from "@/modules/power/powerShared";

interface PowerControlsWidgetProps {
  serverId: string;
  /** "compact" = big number + stats + buttons. "chart" = inline stats + live chart + compact buttons. */
  view?: "compact" | "chart";
  /** Persist a view change via WidgetGrid → widget config. */
  onViewChange?: (view: "compact" | "chart") => void;
}

// Destructive actions — only meaningful while the host is running. Stable ids + i18n
// keys at module load; labels resolved via t() in render.
const DESTRUCTIVE = [
  { id: "soft", labelKey: "power.softOff", icon: PowerOff },
  { id: "off", labelKey: "power.hardOff", icon: PowerOff },
  { id: "reset", labelKey: "power.reset", icon: RotateCcw },
  { id: "cycle", labelKey: "power.cycle", icon: RefreshCw },
] as const;

export function PowerControlsWidget({ serverId, view = "compact", onViewChange }: PowerControlsWidgetProps) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [loading, setLoading] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const online = useBackendOnline();
  const { live, unit, min, max, totalWh, sensorName } = usePowerStats(serverId);
  // 04-W4-01: power state now comes from the `power_status` WS broadcast (+ snapshot
  // replay on connect) via usePowerStore — no more per-widget REST polling. Default
  // to "unknown" until the snapshot/broadcast arrives (within ~500ms of mount).
  const status = usePowerStore((s) => s.statusByServer[serverId]?.status) ?? "unknown";
  // 04-W2-05 / 04-W2-04: cost row OR "Configure tariff" CTA in the compact view.
  // serverId is a STRING (Decision C) — match Server.id by string equality, no cast.
  const currency = useCurrencyStore((s) => s.currency);
  const locale = i18n.resolvedLanguage || "en";
  const server = useServerStore((s) => s.servers.find((srv) => srv.id === serverId));

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
        toast.success(t("power.executed", { action }));
        // Optimistic update — the backend will broadcast the confirmed status shortly.
        usePowerStore.getState().setStatus(serverId, {
          status: action === "on" || action === "reset" || action === "cycle" ? "on" : "off",
        });
      } else {
        toast.error(res.error || t("power.commandFailed"));
      }
    } catch (e: any) {
      toast.error(e.message || t("power.connectionError"));
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

  return (
    <div
      className={cn(
        "flex h-full flex-col gap-0.5 overflow-hidden transition-[filter,opacity]",
        !online && "opacity-50 grayscale"
      )}
    >
      {/* Row 1: status only — chrome icons (reset, view toggle) now live in the
          widget card HEADER via PowerControlsHeaderActions (see registry). */}
      <div className="flex shrink-0 items-center gap-2">
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
          {!online ? t("power.unknown") : isOn ? t("power.online") : isOff ? t("power.offline") : t("power.unknown")}
        </span>
      </div>

      {/* Body — three branches: chart view (chart fills flex-1), compact view (big number),
          or fallback messaging. */}
      {!online ? (
        <div className="flex min-h-0 flex-1 items-center justify-center text-xs text-muted-foreground">
          {t("power.disconnected")}
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
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <span>{t("power.min")} <span className="font-mono text-sm text-foreground">{min != null ? `${Math.round(min)} ${unit}` : "—"}</span></span>
              <span>{t("power.max")} <span className="font-mono text-sm text-foreground">{max != null ? `${Math.round(max)} ${unit}` : "—"}</span></span>
              <span>{t("power.total")} <span className="font-mono text-sm text-foreground">{formatKwh(totalWh)}</span></span>
            </div>
          </div>
          {/* Recharts live chart — fills remaining vertical space */}
          <div className="min-h-0 flex-1">
            <PowerLiveChart serverId={serverId} sensorName={sensorName} />
          </div>
        </>
      ) : live != null ? (
        // Compact view — W2-01 relayout. Gated on `live != null` ALONE (GAP-1 fix):
        // the body shows wattage/Min/Max/Total/cost from usePowerStats.live, not the
        // action-only `power_status` broadcast. PowerStatsWidget already gates this way.
        // Top-aligned column so the Power On button
        // below (its own shrink-0 wrapper) never overlaps the stats at 2x2.
        // Wattage block LEFT, Min/Max/Total + Costo stacked RIGHT.
        // GAP-A (04-13 rework): the cost value / "Configura tariffa" affordance now
        // lives INSIDE the right-side stat stack as a 4th always-visible line (same row
        // format as Min/Max/Total), instead of a separate full-width mt-* block below the
        // wattage|stats row. That earlier block overflowed the shrunk flex-1 body at 2x2
        // and either overlapped the "Accendi" button or (with overflow-y-auto) got clipped
        // below a scroll fold. Folding it into the stat stack keeps the cost/CTA fully
        // visible and non-overlapping at 2x2 with no scrollbar — so the body returns to a
        // plain `min-h-0 flex-1` column (no overflow-y-auto needed).
        <div className="flex min-h-0 flex-1 flex-col gap-0.5">
          {/* Compact view — W2-01 relayout: two-column wattage | Min/Max/Total/Costo */}
          <div className="flex flex-row items-start gap-4">
            {/* Left block — wattage */}
            <div className="flex flex-col">
              <div className="flex items-baseline gap-1.5">
                <Zap className="h-4 w-4 text-violet-400 shrink-0" aria-hidden="true" />
                <span className="font-mono text-2xl font-bold tabular-nums text-foreground">
                  {`${Math.round(live)} ${unit}`}
                </span>
              </div>
              <span className="mt-0.5 text-[10px] uppercase tracking-wider text-muted-foreground">
                {t("power.powerDraw")}
              </span>
            </div>

            {/* Right block — Min / Max / Total + Costo stacked. Renders when there are
                stats to show (sensorName) OR a server to show cost/CTA for (Decision O:
                null-server guard so we never navigate to /settings#server-undefined-cost). */}
            {(sensorName != null || server != null) && (
              <div className="ml-auto flex flex-col gap-0">
                {sensorName != null && (
                  <>
                    <div className="flex items-baseline gap-2 text-xs leading-none text-muted-foreground">
                      <span className="w-10 uppercase tracking-wider text-[10px]">{t("power.min")}</span>
                      <span className="font-mono text-sm text-foreground tabular-nums">
                        {min != null ? `${Math.round(min)} ${unit}` : "—"}
                      </span>
                    </div>
                    <div className="flex items-baseline gap-2 text-xs leading-none text-muted-foreground">
                      <span className="w-10 uppercase tracking-wider text-[10px]">{t("power.max")}</span>
                      <span className="font-mono text-sm text-foreground tabular-nums">
                        {max != null ? `${Math.round(max)} ${unit}` : "—"}
                      </span>
                    </div>
                    <div className="flex items-baseline gap-2 text-xs leading-none text-muted-foreground">
                      <span className="w-10 uppercase tracking-wider text-[10px]">{t("power.total")}</span>
                      <span className="font-mono text-sm text-foreground tabular-nums">
                        {formatKwh(totalWh)}
                      </span>
                    </div>
                  </>
                )}
                {/* Costo line — tariff set → cost value; tariff unset → compact
                    "Configura tariffa" link affordance (still deep-links to settings). */}
                {server != null && (
                  server.cost_per_kwh != null ? (
                    <div className="flex items-baseline gap-2 text-xs leading-none text-muted-foreground">
                      <span className="w-10 uppercase tracking-wider text-[10px]">{t("power.cost")}</span>
                      <span className="font-mono text-sm text-foreground tabular-nums">
                        {formatCurrency((totalWh / 1000) * server.cost_per_kwh, currency, locale)}
                      </span>
                    </div>
                  ) : (
                    <div className="flex items-baseline gap-2 text-xs leading-none text-muted-foreground">
                      <span className="w-10 uppercase tracking-wider text-[10px]">{t("power.cost")}</span>
                      <button
                        type="button"
                        onClick={() => navigate(`/settings#server-${server.id}-cost`)}
                        className="inline-flex items-center gap-1 text-[10px] font-medium text-muted-foreground underline decoration-dashed underline-offset-2 hover:text-foreground"
                        aria-label={t("power.configureTariff")}
                      >
                        <Settings className="h-3 w-3 shrink-0" aria-hidden="true" />
                        {t("power.configureTariff")}
                      </button>
                    </div>
                  )
                )}
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 items-center justify-center text-xs text-muted-foreground">
          {isOff ? t("power.poweredOff") : t("power.noReading")}
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
              <span className="hidden sm:inline">{t("power.onShort")}</span>
            </button>
            {DESTRUCTIVE.map((a) => {
              const Icon = a.icon;
              const confirming = confirm === a.id;
              const label = t(a.labelKey);
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
                  title={label}
                >
                  <Icon className="h-3 w-3" />
                  <span className="truncate">{confirming ? t("power.ok") : label}</span>
                </button>
              );
            })}
          </div>
        ) : (
          <div className="space-y-1">
            <button
              onClick={() => handleAction("on")}
              disabled={busy || isOn}
              className={cn(
                "flex w-full items-center justify-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-medium transition-colors",
                isOn
                  ? "cursor-not-allowed border-border text-muted-foreground/40"
                  : "border-emerald-500/40 bg-emerald-500/10 text-emerald-500 hover:bg-emerald-500/20",
                loading === "on" && "opacity-50"
              )}
            >
              <Power className="h-3.5 w-3.5" />
              {t("power.on")}
            </button>
            <div className="grid grid-cols-2 gap-1 border-t border-border pt-1">
              {DESTRUCTIVE.map((a) => {
                const Icon = a.icon;
                const confirming = confirm === a.id;
                const label = t(a.labelKey);
                return (
                  <button
                    key={a.id}
                    onClick={() => handleAction(a.id)}
                    disabled={busy || isOff}
                    className={cn(
                      "flex items-center justify-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-medium transition-colors",
                      confirming
                        ? "border-red-500 bg-red-500/20 text-red-400"
                        : "border-border text-muted-foreground hover:border-red-500/50 hover:text-red-400",
                      isOff && "cursor-not-allowed opacity-40 hover:border-border hover:text-muted-foreground",
                      loading === a.id && "opacity-50"
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {confirming ? t("power.confirm") : label}
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

/**
 * Header-action chrome for the PowerControls widget — rendered by WidgetGrid in
 * the widget card title bar (not inside the body). Subscribes to the same
 * usePowerStats() hook so the view-toggle stays in sync with the body. Buttons
 * stopPropagation on mousedown so clicking them while the grid is in edit mode
 * doesn't initiate a drag. (Energy-counter reset moved to Settings → Energy
 * Counters in 04-W2-07; no inline reset button here anymore.)
 */
export function PowerControlsHeaderActions({
  serverId,
  view,
  onViewChange,
}: {
  serverId: string;
  view: "compact" | "chart";
  onViewChange?: (v: "compact" | "chart") => void;
}) {
  const { t } = useTranslation();
  const { sensorName } = usePowerStats(serverId);
  if (sensorName == null) return null;
  const isChart = view === "chart";
  return (
    <>
      {onViewChange && (
        <button
          type="button"
          aria-label={isChart ? t("power.switchToCompact") : t("power.switchToChart")}
          title={isChart ? t("power.hideChart") : t("power.showChart")}
          onMouseDown={(e) => e.stopPropagation()}
          onClick={() => onViewChange(isChart ? "compact" : "chart")}
          className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          {isChart ? <LayoutGrid className="h-3 w-3" /> : <LineChartIcon className="h-3 w-3" />}
        </button>
      )}
    </>
  );
}
