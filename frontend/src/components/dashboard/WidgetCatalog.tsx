import { useState, useEffect } from "react";
import { get, put } from "@/api/client";
import { useLayoutStore } from "@/stores/layout-store";
import { useServerStore } from "@/stores/server-store";
import { SUPPORTED_WIDGET_IDS } from "@/modules/registry";
import { cn } from "@/lib/utils";
import { X, LayoutGrid } from "lucide-react";
import { toast } from "sonner";

interface CatalogWidget {
  widget_id: string;
  name: string;
  description: string;
  module_id: string;
  module_name: string;
  default_w: number;
  default_h: number;
  config_schema?: Record<string, unknown>;
}

interface WidgetCatalogProps {
  open: boolean;
  onClose: () => void;
}

export function WidgetCatalog({ open, onClose }: WidgetCatalogProps) {
  const [widgets, setWidgets] = useState<CatalogWidget[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedServer, setSelectedServer] = useState<string>("");
  const addWidget = useLayoutStore((s) => s.addWidget);
  const layout = useLayoutStore((s) => s.layout);
  const servers = useServerStore((s) => s.servers);
  const contextServerId = useServerStore((s) => s.contextServerId);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setSelectedServer(contextServerId || "");
    get<{ widgets: CatalogWidget[] }>("/api/dashboard/widgets")
      .then((data) =>
        setWidgets(
          (data.widgets || []).filter((w) => SUPPORTED_WIDGET_IDS.has(w.widget_id))
        )
      )
      .catch(() => setWidgets([]))
      .finally(() => setLoading(false));
  }, [open, contextServerId]);

  function handleAdd(widget: CatalogWidget) {
    const id = `${widget.widget_id}-${Date.now()}`;
    const newWidget = {
      i: id,
      widget_id: widget.widget_id,
      module_id: widget.module_id,
      server_id: selectedServer || contextServerId || undefined,
      x: 0,
      y: Infinity,
      w: widget.default_w,
      h: widget.default_h,
    };
    addWidget(newWidget);

    // Save layout
    const updatedLayout = [...layout, newWidget];
    put("/api/dashboard/layout", { layout: updatedLayout }).catch(() => {});

    toast.success("Widget added");
    onClose();
  }

  // Group by module
  const grouped = widgets.reduce<Record<string, CatalogWidget[]>>(
    (acc, w) => {
      const key = w.module_name || w.module_id;
      if (!acc[key]) acc[key] = [];
      acc[key].push(w);
      return acc;
    },
    {}
  );

  return (
    <>
      {/* Backdrop */}
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/40"
          onClick={onClose}
        />
      )}

      {/* Panel */}
      <div
        className={cn(
          "fixed right-0 top-0 z-50 flex h-full w-80 flex-col border-l border-border bg-card shadow-xl transition-transform duration-200",
          open ? "translate-x-0" : "translate-x-full"
        )}
      >
        {/* Header */}
        <div className="border-b border-border px-4 py-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">Add Widget</h2>
            <button
              onClick={onClose}
              className="rounded p-1 hover:bg-muted transition-colors"
            >
              <X className="h-4 w-4 text-muted-foreground" />
            </button>
          </div>
          {servers.length > 1 && (
            <select
              aria-label="Assign widget to server"
              value={selectedServer || contextServerId || ""}
              onChange={(e) => setSelectedServer(e.target.value)}
              className="mt-3 w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm"
            >
              {servers.map((server) => (
                <option key={server.id} value={server.id}>
                  {server.name}
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto p-4">
          {loading && (
            <div className="flex items-center justify-center py-12">
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
            </div>
          )}

          {!loading && widgets.length === 0 && (
            <p className="py-8 text-center text-xs text-muted-foreground">
              No widgets available.
            </p>
          )}

          {!loading &&
            Object.entries(grouped).map(([moduleName, moduleWidgets]) => (
              <div key={moduleName} className="mb-5">
                <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  {moduleName}
                </h3>
                <div className="space-y-2">
                  {moduleWidgets.map((w) => (
                    <button
                      key={w.widget_id}
                      onClick={() => handleAdd(w)}
                      className="flex w-full items-start gap-3 rounded-lg border border-border p-3 text-left hover:bg-muted/50 transition-colors"
                    >
                      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted">
                        <LayoutGrid className="h-4 w-4 text-muted-foreground" />
                      </div>
                      <div className="min-w-0">
                        <p className="text-sm font-medium leading-tight">
                          {w.name}
                        </p>
                        <p className="mt-0.5 text-xs text-muted-foreground line-clamp-2">
                          {w.description}
                        </p>
                        <p className="mt-1 text-[10px] text-muted-foreground">
                          {w.default_w}x{w.default_h}
                        </p>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            ))}
        </div>
      </div>
    </>
  );
}
