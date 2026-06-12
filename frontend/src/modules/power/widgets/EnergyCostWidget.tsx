import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { Settings, Zap, Download } from "lucide-react";
import { useServerStore } from "@/stores/server-store";
import { useCurrencyStore } from "@/stores/currency-store";
import { useRangeStore } from "@/stores/range-store";
import { formatCurrency } from "@/lib/currency";
import { usePowerStats, EnergyKwhChart, formatKwh } from "@/modules/power/powerShared";
import { exportSensorCsv } from "@/modules/power/exportCsv";

interface Props {
  /** Server IDs are STRINGS end-to-end (Decision C). */
  serverId: string;
  w: number;
  h: number;
}

/**
 * Header toolbar action — Export CSV button (04-W6-03). Downloads the picked power
 * sensor's history for the current useRangeStore range from /api/system/history-csv.
 * Rendered in the card header via the registry's headerActions slot.
 */
export function EnergyCostHeaderActions({ serverId }: { serverId: string }) {
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
 * Energy Cost widget (04-W2-06).
 *   - 2x2: large cost figure + range label + kWh (cost-only summary).
 *   - 3x2: inline cost row + cumulative kWh chart (Decision N — EnergyKwhChart,
 *     NOT the watts chart re-skinned).
 * Shows "Configure tariff" CTA when cost_per_kwh is null; renders nothing when the
 * server is missing from the store (Decision O — null guard).
 */
export function EnergyCostWidget({ serverId, w, h }: Props) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage || "en";
  const server = useServerStore((s) => s.servers.find((srv) => srv.id === serverId));
  const currency = useCurrencyStore((s) => s.currency);
  const range = useRangeStore((s) => s.range);
  const stats = usePowerStats(serverId);
  const navigate = useNavigate();

  // Decision O — null-server guard (prevents /settings#server-undefined-cost).
  if (server == null) return null;

  // range-store values are "live" | "1h" | "24h" | "7d" — map to the pre-existing
  // power.rangeLabel* keys (Plan 01 Task 0 catalogs). No new i18n keys.
  const rangeLabel = (
    range === "live" ? t("power.rangeLabelLive") :
    range === "1h"   ? t("power.rangeLabelHour") :
    range === "24h"  ? t("power.rangeLabelDay")  :
    range === "7d"   ? t("power.rangeLabelWeek") : ""
  ).toUpperCase();

  const kwh = stats.totalWh / 1000;
  const cost = server.cost_per_kwh != null ? kwh * server.cost_per_kwh : null;
  const isChartSize = w >= 3 || h >= 3;

  if (cost == null) {
    return (
      <div className="flex h-full flex-col">
        <div className="flex flex-1 flex-col items-center justify-center gap-2 p-3 text-center">
          <Zap className="h-6 w-6 text-violet-400" aria-hidden="true" />
          <h3 className="text-sm font-semibold text-foreground">{t("widget.energyNoTariffTitle")}</h3>
          <p className="max-w-[260px] text-xs text-muted-foreground">{t("widget.energyNoTariffBody")}</p>
          <button
            type="button"
            onClick={() => navigate(`/settings#server-${server.id}-cost`)}
            className="mt-1 inline-flex items-center gap-1.5 rounded-md border border-dashed border-border px-2.5 py-1 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground min-h-9 md:min-h-7"
            aria-label={t("power.configureTariff")}
          >
            <Settings className="h-3 w-3" aria-hidden="true" />
            {t("power.configureTariff")}
          </button>
        </div>
        {isChartSize && (
          <div className="min-h-0 flex-1 px-2 pb-2">
            <EnergyKwhChart serverId={serverId} />
          </div>
        )}
      </div>
    );
  }

  if (!isChartSize) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-1 px-3">
        <span className="font-mono text-3xl font-bold tabular-nums text-foreground">
          {formatCurrency(cost, currency, locale)}
        </span>
        <span className="text-xs uppercase tracking-wider text-muted-foreground">{rangeLabel}</span>
        <span className="text-sm tabular-nums text-muted-foreground">{formatKwh(stats.totalWh)}</span>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-baseline gap-3 px-3 pt-2">
        <span className="font-mono text-2xl font-bold tabular-nums text-foreground">
          {formatCurrency(cost, currency, locale)}
        </span>
        <span className="text-xs text-muted-foreground">
          {rangeLabel} · {formatKwh(stats.totalWh)}
        </span>
      </div>
      <div className="min-h-0 flex-1 px-2 pb-2">
        <EnergyKwhChart serverId={serverId} />
      </div>
    </div>
  );
}
