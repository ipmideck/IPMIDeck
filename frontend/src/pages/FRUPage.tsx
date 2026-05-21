import { useEffect, useState } from "react";
import { Header } from "@/components/layout/Header";
import { useServerStore } from "@/stores/server-store";
import { get, post } from "@/api/client";
import { toast } from "sonner";
import { EmptyState } from "@/components/common/EmptyState";
import { RefreshCw, Copy, ServerOff, CircuitBoard } from "lucide-react";

interface FRUData {
  sections: Record<string, { field: string; value: string }[]>;
  fetched_at: string | null;
}

export default function FRUPage() {
  const contextServerId = useServerStore((s) => s.contextServerId);
  const [data, setData] = useState<FRUData | null>(null);
  const [loading, setLoading] = useState(false);

  const loadFRU = async () => {
    if (!contextServerId) return;
    try {
      const res = await get<FRUData>(`/api/modules/fru/${contextServerId}`);
      setData(res);
    } catch { /* ignore */ }
  };

  const refresh = async () => {
    if (!contextServerId) return;
    setLoading(true);
    try {
      await post(`/api/modules/fru/${contextServerId}/refresh`);
      await loadFRU();
      toast.success("FRU data refreshed");
    } catch {
      toast.error("Failed to refresh FRU");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadFRU(); }, [contextServerId]);

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    toast.success("Copied to clipboard");
  };

  const sections = data?.sections || {};
  const hasSections = Object.keys(sections).length > 0;

  return (
    <>
      <Header title="Hardware">
        <button onClick={refresh} disabled={loading} className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted">
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} /> Refresh
        </button>
      </Header>
      <div className="flex-1 overflow-auto p-6">
        {!hasSections ? (
          !contextServerId ? (
            <EmptyState
              icon={ServerOff}
              title="No server selected"
              description="Select a server from the sidebar to inspect its hardware inventory."
            />
          ) : (
            <EmptyState
              icon={CircuitBoard}
              title="No hardware data"
              description="This server returned no FRU inventory. Check the BMC connection."
            />
          )
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {Object.entries(sections).map(([section, fields]) => (
              <div key={section} className="rounded-lg border border-border bg-card p-5">
                <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">{section}</h3>
                <div className="space-y-2">
                  {fields.map((f, i) => (
                    <div key={i} className="flex items-center justify-between gap-4">
                      <span className="text-xs text-muted-foreground truncate">{f.field}</span>
                      <div className="flex items-center gap-1">
                        <span className="font-mono text-xs font-medium truncate max-w-[180px]">{f.value}</span>
                        {(f.field.toLowerCase().includes("serial") || f.field.toLowerCase().includes("part")) && (
                          <button onClick={() => copyToClipboard(f.value)} className="rounded p-0.5 hover:bg-muted">
                            <Copy className="h-3 w-3 text-muted-foreground" />
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
            {data?.fetched_at && (
              <p className="col-span-full text-xs text-muted-foreground">
                Last updated: {new Date(data.fetched_at).toLocaleString()}
              </p>
            )}
          </div>
        )}
      </div>
    </>
  );
}
