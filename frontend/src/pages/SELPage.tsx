import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Header } from "@/components/layout/Header";
import { useServerStore } from "@/stores/server-store";
import { useBackendOnline } from "@/stores/connection-store";
import { get, post } from "@/api/client";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/common/EmptyState";
import {
  RefreshCw,
  Download,
  ServerOff,
  FileClock,
  AlertOctagon,
  AlertTriangle,
  Info,
} from "lucide-react";

interface SELEvent {
  event_id: string;
  timestamp: string;
  sensor_name: string;
  event_type: string;
  description: string;
  severity: string;
}

// D-04 (colorblind): severity is never conveyed by color alone. Each severity
// pairs a distinct lucide icon SHAPE + a foundation semantic color token
// (--color-danger/warning/info) + a translated text label, so it stays
// unambiguous in grayscale and for red-green color-vision deficiency. Same
// pattern the Dashboard pilot (06-02) established for widget status.
type SeverityStyle = { icon: typeof AlertOctagon; badge: string; labelKey: string };

const SEVERITY: Record<string, SeverityStyle> = {
  critical: { icon: AlertOctagon, badge: "bg-danger/10 text-danger", labelKey: "sel.severityCritical" },
  warning: { icon: AlertTriangle, badge: "bg-warning/10 text-warning", labelKey: "sel.severityWarning" },
  info: { icon: Info, badge: "bg-info/10 text-info", labelKey: "sel.severityInfo" },
};

export default function SELPage() {
  const { t } = useTranslation();
  const contextServerId = useServerStore((s) => s.contextServerId);
  const [events, setEvents] = useState<SELEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<string>("all");
  const online = useBackendOnline();

  const loadEvents = async () => {
    if (!contextServerId) return;
    try {
      const data = await get<{ events: SELEvent[] }>(`/api/modules/sel/${contextServerId}`);
      setEvents(data.events || []);
    } catch { /* ignore */ }
  };

  const refresh = async () => {
    if (!contextServerId) return;
    setLoading(true);
    try {
      await post(`/api/modules/sel/${contextServerId}/refresh`);
      await loadEvents();
      toast.success(t("sel.refreshed"));
    } catch {
      toast.error(t("sel.refreshFailed"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadEvents(); }, [contextServerId]);

  const filtered = filter === "all" ? events : events.filter((e) => e.severity === filter);

  // Severity badge: icon shape + semantic token + translated label (D-04).
  const severityBadge = (s: string) => {
    const style = SEVERITY[s];
    const Icon = style?.icon ?? Info;
    const cls = style?.badge ?? "bg-muted text-muted-foreground";
    const label = style ? t(style.labelKey) : s;
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold",
          cls
        )}
      >
        <Icon className="h-3 w-3 shrink-0" aria-hidden="true" />
        {label}
      </span>
    );
  };

  return (
    <>
      <Header title={t("sel.title")}>
        <div className="flex items-center gap-2">
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="min-h-11 rounded-md border border-border bg-background px-2 py-1 text-base md:min-h-0 md:text-xs"
          >
            <option value="all">{t("sel.filterAll")}</option>
            <option value="critical">{t("sel.filterCritical")}</option>
            <option value="warning">{t("sel.filterWarning")}</option>
            <option value="info">{t("sel.filterInfo")}</option>
          </select>
          <a
            href={contextServerId ? `/api/modules/sel/${contextServerId}/export?format=csv` : "#"}
            className="flex min-h-11 items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted md:min-h-0"
          >
            <Download className="h-3 w-3" /> {t("sel.exportCsv")}
          </a>
          <button
            onClick={refresh}
            disabled={loading || !online}
            title={!online ? t("header.backendDisconnected") : undefined}
            className="flex min-h-11 items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 md:min-h-0"
          >
            <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} /> {t("sel.refresh")}
          </button>
        </div>
      </Header>
      <div className="flex-1 overflow-auto p-6">
        {filtered.length === 0 ? (
          !contextServerId ? (
            <EmptyState
              icon={ServerOff}
              title={t("sel.noServerTitle")}
              description={t("sel.noServerDescription")}
            />
          ) : (
            <EmptyState
              icon={FileClock}
              title={t("sel.emptyTitle")}
              description={t("sel.emptyDescription")}
            />
          )
        ) : (
          <div className="mx-auto max-w-6xl">
            {/* At-a-glance count — Visibility of system status. */}
            <div className="mb-3 text-xs font-medium text-muted-foreground">
              {t("sel.eventCount", { count: filtered.length })}
            </div>

            {/* Desktop (>= md): table — earned hierarchy via blueprint layers
                (card surface + shadow off the canvas; tinted surface-2 sticky
                header band; value-first lead column). No new color (D-06). */}
            <div className="hidden overflow-hidden rounded-lg border border-border bg-card shadow-sm md:block">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted">
                    <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t("sel.colSeverity")}</th>
                    <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t("sel.colTimestamp")}</th>
                    <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t("sel.colSensor")}</th>
                    <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t("sel.colEvent")}</th>
                    <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t("sel.colDescription")}</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((ev, i) => (
                    <tr key={i} className="border-b border-border/60 last:border-0 hover:bg-muted/40">
                      <td className="px-4 py-2.5 align-middle">{severityBadge(ev.severity)}</td>
                      <td className="px-4 py-2.5 align-middle whitespace-nowrap font-mono text-xs text-muted-foreground">{ev.timestamp}</td>
                      <td className="px-4 py-2.5 align-middle text-sm font-medium text-foreground">{ev.sensor_name}</td>
                      <td className="px-4 py-2.5 align-middle text-xs text-foreground">{ev.event_type}</td>
                      <td className="px-4 py-2.5 align-middle text-xs text-muted-foreground">{ev.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Mobile (< md): card list — severity badge leftmost in the primary
                row, sensor as the value-first lead (Phase-4 reflow re-skinned,
                not reworked). */}
            <div className="space-y-2 md:hidden">
              {filtered.map((ev, i) => (
                <div key={i} className="space-y-1.5 rounded-lg border border-border bg-card p-3 shadow-sm">
                  <div className="flex items-center gap-2">
                    {severityBadge(ev.severity)}
                    <span className="text-sm font-semibold text-foreground">{ev.sensor_name}</span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">{t("sel.colEvent")}:</span> {ev.event_type}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">{t("sel.colTimestamp")}:</span>{" "}
                    <span className="font-mono">{ev.timestamp}</span>
                  </div>
                  {ev.description && (
                    <div className="text-xs text-muted-foreground">
                      <span className="font-medium text-foreground">{t("sel.colDescription")}:</span> {ev.description}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
