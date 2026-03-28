import { useEffect } from "react";
import { Header } from "@/components/layout/Header";
import { WidgetGrid } from "@/components/dashboard/WidgetGrid";
import { useLayoutStore } from "@/stores/layout-store";
import { useServerStore } from "@/stores/server-store";
import { get } from "@/api/client";
import { Plus } from "lucide-react";

export default function Dashboard() {
  const { layout, setLayout } = useLayoutStore();
  const contextServerId = useServerStore((s) => s.contextServerId);
  const servers = useServerStore((s) => s.servers);

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
        <div className="flex items-center gap-1 rounded-md bg-muted p-0.5">
          <button className="rounded-sm bg-background px-2.5 py-1 text-xs font-medium shadow-sm">
            Live
          </button>
          <button className="rounded-sm px-2.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground">
            1H
          </button>
          <button className="rounded-sm px-2.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground">
            24H
          </button>
          <button className="rounded-sm px-2.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground">
            7D
          </button>
        </div>
      </Header>
      <div className="flex-1 overflow-auto p-6">
        {hasWidgets && hasServers ? (
          <WidgetGrid />
        ) : (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-xl bg-muted">
              <Plus className="h-6 w-6 text-muted-foreground" />
            </div>
            <h2 className="text-lg font-semibold">
              {hasServers ? "Your dashboard is empty" : "No servers configured"}
            </h2>
            <p className="mt-1 max-w-sm text-sm text-muted-foreground">
              {hasServers
                ? "Widgets will appear automatically when sensor data arrives."
                : "Add a server in Settings to start monitoring."}
            </p>
          </div>
        )}
      </div>
    </>
  );
}
