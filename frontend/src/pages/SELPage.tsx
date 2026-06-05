import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Header } from "@/components/layout/Header";
import { useServerStore } from "@/stores/server-store";
import { useBackendOnline } from "@/stores/connection-store";
import { get, post } from "@/api/client";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/common/EmptyState";
import { RefreshCw, Download, ServerOff, FileClock } from "lucide-react";

interface SELEvent {
  event_id: string;
  timestamp: string;
  sensor_name: string;
  event_type: string;
  description: string;
  severity: string;
}

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

  const severityBadge = (s: string) => {
    const cls = s === "critical" ? "bg-red-500/10 text-red-500" : s === "warning" ? "bg-yellow-500/10 text-yellow-500" : "bg-blue-500/10 text-blue-500";
    const label =
      s === "critical" ? t("sel.severityCritical")
      : s === "warning" ? t("sel.severityWarning")
      : s === "info" ? t("sel.severityInfo")
      : s;
    return <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium", cls)}>{label}</span>;
  };

  return (
    <>
      <Header title={t("sel.title")}>
        <div className="flex items-center gap-2">
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="rounded-md border border-border bg-background px-2 py-1 text-xs"
          >
            <option value="all">{t("sel.filterAll")}</option>
            <option value="critical">{t("sel.filterCritical")}</option>
            <option value="warning">{t("sel.filterWarning")}</option>
            <option value="info">{t("sel.filterInfo")}</option>
          </select>
          <a
            href={contextServerId ? `/api/modules/sel/${contextServerId}/export?format=csv` : "#"}
            className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted"
          >
            <Download className="h-3 w-3" /> {t("sel.exportCsv")}
          </a>
          <button
            onClick={refresh}
            disabled={loading || !online}
            title={!online ? t("header.backendDisconnected") : undefined}
            className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
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
          <div className="rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/50">
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">{t("sel.colSeverity")}</th>
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">{t("sel.colTimestamp")}</th>
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">{t("sel.colSensor")}</th>
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">{t("sel.colEvent")}</th>
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">{t("sel.colDescription")}</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((ev, i) => (
                  <tr key={i} className="border-b border-border/50 hover:bg-muted/30">
                    <td className="px-4 py-2">{severityBadge(ev.severity)}</td>
                    <td className="px-4 py-2 font-mono text-xs text-muted-foreground">{ev.timestamp}</td>
                    <td className="px-4 py-2 text-xs">{ev.sensor_name}</td>
                    <td className="px-4 py-2 text-xs">{ev.event_type}</td>
                    <td className="px-4 py-2 text-xs text-muted-foreground">{ev.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
