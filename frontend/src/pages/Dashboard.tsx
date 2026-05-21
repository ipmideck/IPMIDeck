import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Header } from "@/components/layout/Header";
import { WidgetGrid } from "@/components/dashboard/WidgetGrid";
import { WidgetCatalog } from "@/components/dashboard/WidgetCatalog";
import { useLayoutStore } from "@/stores/layout-store";
import { useServerStore } from "@/stores/server-store";
import { useRangeStore } from "@/stores/range-store";
import { EmptyState } from "@/components/common/EmptyState";
import { cn } from "@/lib/utils";
import { get } from "@/api/client";
import { Plus, Server, LayoutGrid } from "lucide-react";

export default function Dashboard() {
  const { layout, setLayout } = useLayoutStore();
  const contextServerId = useServerStore((s) => s.contextServerId);
  const servers = useServerStore((s) => s.servers);
  const range = useRangeStore((s) => s.range);
  const setRange = useRangeStore((s) => s.setRange);
  const navigate = useNavigate();
  const [catalogOpen, setCatalogOpen] = useState(false);

  // Load layout from backend
  useEffect(() => {
    async function loadLayout() {
      try {
        const data = await get<{ layout: any[] }>("/api/dashboard/layout");
        if (data.layout?.length > 0) {
          setLayout(data.layout);
        }
      } catch { /* ignore */ }
    }
    loadLayout();
  }, [setLayout]);

  const hasWidgets = layout.length > 0;
  const hasServers = servers.length > 0;

  return (
    <>
      <Header title="Dashboard">
        <button
          onClick={() => setCatalogOpen(true)}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90 transition-colors"
        >
          <Plus className="h-3.5 w-3.5" />
          Add Widget
        </button>
        <div className="flex items-center gap-1 rounded-md bg-muted p-0.5">
          {(
            [
              ["Live", "live"],
              ["1H", "1h"],
              ["24H", "24h"],
              ["7D", "7d"],
            ] as const
          ).map(([label, value]) => (
            <button
              key={value}
              onClick={() => setRange(value)}
              className={cn(
                "rounded-sm px-2.5 py-1 text-xs font-semibold",
                range === value
                  ? "bg-background shadow-sm text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </Header>
      <div className="flex-1 overflow-auto p-6">
        {hasWidgets && hasServers ? (
          <WidgetGrid />
        ) : !hasServers ? (
          <EmptyState
            icon={Server}
            title="No servers configured"
            description="Add a server to start monitoring your hardware."
            action={{ label: "Add a Server", onClick: () => navigate("/settings") }}
          />
        ) : (
          <EmptyState
            icon={LayoutGrid}
            title="Your dashboard is empty"
            description="Add widgets to build your personalized monitoring view."
            action={{ label: "Add Your First Widget", onClick: () => setCatalogOpen(true) }}
          />
        )}
      </div>
      <WidgetCatalog open={catalogOpen} onClose={() => setCatalogOpen(false)} />
    </>
  );
}
