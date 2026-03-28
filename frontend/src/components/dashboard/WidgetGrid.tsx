import { useLayoutStore, type WidgetLayout } from "@/stores/layout-store";
import { useServerStore } from "@/stores/server-store";
import { renderWidget, getWidgetTitle } from "@/modules/registry";
import { X } from "lucide-react";
import { put } from "@/api/client";

/**
 * Simple CSS Grid-based widget layout.
 * Widgets are placed using grid-column/grid-row spans from the layout data.
 * Drag-and-drop reordering deferred to Phase 2 (react-grid-layout v3 / dnd-kit).
 */
export function WidgetGrid() {
  const { layout, removeWidget } = useLayoutStore();
  const contextServerId = useServerStore((s) => s.contextServerId);

  const handleRemove = (id: string) => {
    removeWidget(id);
    const newLayout = layout.filter((w) => w.i !== id);
    put("/api/dashboard/layout", { layout: newLayout }).catch(() => {});
  };

  if (!contextServerId) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
        No server configured
      </div>
    );
  }

  return (
    <div
      className="grid gap-4"
      style={{
        gridTemplateColumns: "repeat(6, 1fr)",
        gridAutoRows: "100px",
      }}
    >
      {layout.map((item) => (
        <div
          key={item.i}
          className="group relative rounded-lg border border-border bg-card overflow-hidden"
          style={{
            gridColumn: `span ${item.w}`,
            gridRow: `span ${item.h}`,
          }}
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b border-border/50 px-3 py-2">
            <span className="text-[11px] font-medium text-muted-foreground">
              {getWidgetTitle(item)}
            </span>
            <button
              onClick={() => handleRemove(item.i)}
              className="opacity-0 group-hover:opacity-100 transition-opacity rounded p-0.5 hover:bg-muted"
            >
              <X className="h-3 w-3 text-muted-foreground" />
            </button>
          </div>
          {/* Body */}
          <div className="p-3" style={{ height: "calc(100% - 33px)" }}>
            {renderWidget(item, contextServerId)}
          </div>
        </div>
      ))}
    </div>
  );
}
