import { Zap, RefreshCw, WifiOff } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { useBackendOnline } from "@/stores/connection-store";
import { usePowerStats, PowerLiveChart, formatKwh } from "@/modules/power/powerShared";

interface PowerStatsWidgetProps {
  serverId: string;
}

/**
 * Read-only twin of the chart view inside PowerControlsWidget — same recharts live
 * chart, no power buttons. Useful for monitoring-only dashboards.
 */
export function PowerStatsWidget({ serverId }: PowerStatsWidgetProps) {
  const { t } = useTranslation();
  const online = useBackendOnline();
  const { live, unit, min, max, totalWh, sensorName, reset } = usePowerStats(serverId);

  if (!serverId) {
    return <div className="flex h-full items-center justify-center text-muted-foreground">—</div>;
  }

  return (
    <div
      className={cn(
        "flex h-full flex-col gap-1.5 transition-[filter,opacity]",
        !online && "opacity-50 grayscale"
      )}
    >
      {/* Header: inline live + stats + reset button */}
      <div className="flex shrink-0 flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div className="flex items-baseline gap-1">
          <Zap className="h-4 w-4 self-center text-violet-400" />
          <span className="font-mono text-xl font-bold tabular-nums">
            {online && live != null ? Math.round(live) : "—"}
          </span>
          <span className="text-xs text-muted-foreground">{unit}</span>
          <span className="ml-1 text-[10px] uppercase tracking-wider text-muted-foreground">
            {t("power.powerDraw")}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span>{t("power.min")} <span className="font-mono text-sm text-foreground">{online && min != null ? `${Math.round(min)} ${unit}` : "—"}</span></span>
            <span>{t("power.max")} <span className="font-mono text-sm text-foreground">{online && max != null ? `${Math.round(max)} ${unit}` : "—"}</span></span>
            <span>{t("power.total")} <span className="font-mono text-sm text-foreground">{online ? formatKwh(totalWh) : "—"}</span></span>
          </div>
          {sensorName != null && (
            <button
              type="button"
              onMouseDown={(e) => e.stopPropagation()}
              onClick={reset}
              title={t("power.resetCounters")}
              className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <RefreshCw className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>

      {/* Chart — fills the body */}
      <div className="relative min-h-0 flex-1">
        <PowerLiveChart serverId={serverId} sensorName={sensorName} />
        {!online && (
          <div className="pointer-events-none absolute bottom-1 left-1">
            <div className="flex items-center gap-1.5 rounded-md border border-red-500/30 bg-card/95 px-2 py-0.5 text-[10px] font-medium text-red-500 shadow">
              <WifiOff className="h-3 w-3" />
              {t("power.disconnected")}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
