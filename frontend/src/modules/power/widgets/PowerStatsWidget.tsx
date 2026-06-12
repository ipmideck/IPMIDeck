import { Zap, WifiOff, Settings, Download } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { useBackendOnline } from "@/stores/connection-store";
import { useServerStore } from "@/stores/server-store";
import { useCurrencyStore } from "@/stores/currency-store";
import { useRangeStore } from "@/stores/range-store";
import { formatCurrency } from "@/lib/currency";
import { usePowerStats, PowerLiveChart, formatKwh } from "@/modules/power/powerShared";
import { exportSensorCsv } from "@/modules/power/exportCsv";

interface PowerStatsWidgetProps {
  serverId: string;
}

/**
 * Header toolbar action — Export CSV button (04-W6-03). Downloads the picked power
 * sensor's history for the current useRangeStore range from /api/system/history-csv.
 * Rendered in the card header via the registry's headerActions slot.
 */
export function PowerStatsHeaderActions({ serverId }: { serverId: string }) {
  const { t } = useTranslation();
  const { sensorName } = usePowerStats(serverId);
  const range = useRangeStore((s) => s.range);
  return (
    <button
      type="button"
      onClick={() => exportSensorCsv(serverId, sensorName, range)}
      disabled={!sensorName}
      aria-label={t("widget.exportCsv")}
      title={t("widget.exportCsv")}
      className="rounded-md p-1 text-muted-foreground min-h-9 md:min-h-7 hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
    >
      <Download className="h-3.5 w-3.5" aria-hidden="true" />
    </button>
  );
}

/**
 * Read-only twin of the chart view inside PowerControlsWidget — same recharts live
 * chart, no power buttons. Useful for monitoring-only dashboards.
 */
export function PowerStatsWidget({ serverId }: PowerStatsWidgetProps) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const online = useBackendOnline();
  const { live, unit, min, max, totalWh, sensorName } = usePowerStats(serverId);
  // 04-W2-05 / 04-W2-04: cost line next to Min/Max/Total, OR "Configure tariff" CTA.
  // serverId is a STRING (Decision C) — match Server.id by string equality, no cast.
  const currency = useCurrencyStore((s) => s.currency);
  const locale = i18n.resolvedLanguage || "en";
  const server = useServerStore((s) => s.servers.find((srv) => srv.id === serverId));

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
      {/* Header: inline live + stats. Energy-counter reset moved to
          Settings → Energy Counters (04-W2-07). */}
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
          {/* Cost line OR Configure tariff CTA — Decision O: null-server guard so we
              never navigate to /settings#server-undefined-cost. */}
          {server == null ? null : (
            server.cost_per_kwh != null ? (
              <div className="flex items-baseline gap-2 text-xs text-muted-foreground">
                <span className="w-10 uppercase tracking-wider text-[10px]">{t("power.cost")}</span>
                <span className="font-mono text-sm text-foreground tabular-nums">
                  {online ? formatCurrency((totalWh / 1000) * server.cost_per_kwh, currency, locale) : "—"}
                </span>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => navigate(`/settings#server-${server.id}-cost`)}
                className="inline-flex items-center gap-1.5 rounded-md border border-dashed border-border px-2.5 py-1 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground min-h-9 md:min-h-7"
                aria-label={t("power.configureTariff")}
              >
                <Settings className="h-3 w-3" aria-hidden="true" />
                {t("power.configureTariff")}
              </button>
            )
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
