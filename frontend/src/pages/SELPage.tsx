import { useEffect, useState } from "react";
import { Header } from "@/components/layout/Header";
import { useServerStore } from "@/stores/server-store";
import { get, post } from "@/api/client";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { RefreshCw, Download, Trash2 } from "lucide-react";

interface SELEvent {
  event_id: string;
  timestamp: string;
  sensor_name: string;
  event_type: string;
  description: string;
  severity: string;
}

export default function SELPage() {
  const contextServerId = useServerStore((s) => s.contextServerId);
  const [events, setEvents] = useState<SELEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<string>("all");

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
      toast.success("SEL refreshed from BMC");
    } catch {
      toast.error("Failed to refresh SEL");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadEvents(); }, [contextServerId]);

  const filtered = filter === "all" ? events : events.filter((e) => e.severity === filter);

  const severityBadge = (s: string) => {
    const cls = s === "critical" ? "bg-red-500/10 text-red-500" : s === "warning" ? "bg-yellow-500/10 text-yellow-500" : "bg-blue-500/10 text-blue-500";
    return <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium", cls)}>{s}</span>;
  };

  return (
    <>
      <Header title="Event Log">
        <div className="flex items-center gap-2">
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="rounded-md border border-border bg-background px-2 py-1 text-xs"
          >
            <option value="all">All</option>
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </select>
          <a
            href={contextServerId ? `/api/modules/sel/${contextServerId}/export?format=csv` : "#"}
            className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted"
          >
            <Download className="h-3 w-3" /> CSV
          </a>
          <button onClick={refresh} disabled={loading} className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted">
            <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} /> Refresh
          </button>
        </div>
      </Header>
      <div className="flex-1 overflow-auto p-6">
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <h2 className="text-lg font-semibold">No events</h2>
            <p className="mt-1 text-sm text-muted-foreground">Click Refresh to load events from the BMC.</p>
            <button onClick={refresh} className="mt-4 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground">
              Refresh from BMC
            </button>
          </div>
        ) : (
          <div className="rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/50">
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">Severity</th>
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">Timestamp</th>
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">Sensor</th>
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">Event</th>
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-muted-foreground">Description</th>
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
