import { useCallback, useRef, useState, useEffect } from "react";
import { ResponsiveGridLayout } from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import { useLayoutStore } from "@/stores/layout-store";
import { useServerStore } from "@/stores/server-store";
import { renderWidget, getWidgetTitle } from "@/modules/registry";
import { ErrorBoundary, WidgetErrorFallback } from "@/components/ErrorBoundary";
import { X, ChevronDown } from "lucide-react";
import { put } from "@/api/client";

export function WidgetGrid() {
  const { layout, removeWidget, updateLayout, setWidgetServer } = useLayoutStore();
  const contextServerId = useServerStore((s) => s.contextServerId);
  const servers = useServerStore((s) => s.servers);
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(1000);
  const [openTagId, setOpenTagId] = useState<string | null>(null);
  const showIdentity = servers.length > 1;

  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setWidth(entry.contentRect.width);
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const handleRemove = useCallback((id: string) => {
    removeWidget(id);
    const newLayout = layout.filter((w) => w.i !== id);
    put("/api/dashboard/layout", { layout: newLayout }).catch(() => {});
  }, [layout, removeWidget]);

  const handleLayoutChange = useCallback((newLayout: readonly any[]) => {
    const updates = newLayout.map((l: any) => ({
      i: l.i,
      x: l.x,
      y: l.y,
      w: l.w,
      h: l.h,
    }));
    updateLayout(updates);
    const merged = layout.map((item) => {
      const u = updates.find((up: any) => up.i === item.i);
      return u ? { ...item, ...u } : item;
    });
    put("/api/dashboard/layout", { layout: merged }).catch(() => {});
  }, [layout, updateLayout]);

  if (!contextServerId) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
        No server configured
      </div>
    );
  }

  const gridLayout = layout.map((item) => ({
    i: item.i,
    x: item.x,
    y: item.y,
    w: item.w,
    h: item.h,
    minW: 1,
    minH: 1,
  }));

  return (
    <div ref={containerRef}>
      <ResponsiveGridLayout
        className="react-grid-layout"
        width={width}
        layouts={{ lg: gridLayout }}
        breakpoints={{ lg: 1280, md: 768, sm: 0 }}
        cols={{ lg: 6, md: 4, sm: 2 }}
        rowHeight={120}
        margin={[16, 16] as const}
        containerPadding={[0, 0] as const}
        dragConfig={{ enabled: true, handle: ".widget-drag-handle" }}
        resizeConfig={{ enabled: true }}
        onLayoutChange={handleLayoutChange}
      >
        {layout.map((item) => {
          const widgetServerId = item.server_id || contextServerId;
          const widgetServer = servers.find((s) => s.id === widgetServerId);
          const accent = showIdentity && widgetServer;
          return (
            <div
              key={item.i}
              className={`group relative rounded-lg border border-border bg-card shadow-sm overflow-hidden${accent ? " border-l-[3px]" : ""}`}
              style={accent ? { borderLeftColor: widgetServer.color } : undefined}
            >
              <div className="widget-drag-handle flex items-center justify-between border-b border-border/50 px-3 py-2 cursor-grab active:cursor-grabbing">
                <span className="text-[11px] font-semibold text-muted-foreground select-none">
                  {getWidgetTitle(item)}
                </span>
                <div className="flex items-center gap-1">
                  {accent && (
                    <div className="relative">
                      <button
                        aria-label="Switch server"
                        onMouseDown={(e) => e.stopPropagation()}
                        onClick={() => setOpenTagId((prev) => (prev === item.i ? null : item.i))}
                        className="flex items-center gap-1 text-[11px] font-semibold text-muted-foreground"
                      >
                        <span
                          className="h-2 w-2 rounded-full"
                          style={{ background: widgetServer.color }}
                        />
                        {widgetServer.name}
                        <ChevronDown className="h-3 w-3 text-muted-foreground" />
                      </button>
                      {openTagId === item.i && (
                        <div
                          onMouseDown={(e) => e.stopPropagation()}
                          className="absolute right-0 top-full z-50 mt-1 min-w-40 rounded-lg border border-border bg-popover text-popover-foreground shadow-lg"
                        >
                          <div className="max-h-60 overflow-y-auto py-1">
                            {servers.map((s) => (
                              <button
                                key={s.id}
                                onMouseDown={(e) => e.stopPropagation()}
                                onClick={() => {
                                  setWidgetServer(item.i, s.id);
                                  const merged = layout.map((w) =>
                                    w.i === item.i ? { ...w, server_id: s.id } : w
                                  );
                                  put("/api/dashboard/layout", { layout: merged }).catch(() => {});
                                  setOpenTagId(null);
                                }}
                                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-[13px] hover:bg-muted text-left"
                              >
                                <span
                                  className="h-2 w-2 shrink-0 rounded-full"
                                  style={{ background: s.color }}
                                />
                                <span className="truncate">{s.name}</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                  <button
                    onClick={() => handleRemove(item.i)}
                    className="opacity-0 group-hover:opacity-100 transition-opacity rounded p-0.5 hover:bg-muted"
                  >
                    <X className="h-3 w-3 text-muted-foreground" />
                  </button>
                </div>
              </div>
              <div className="p-3" style={{ height: "calc(100% - 33px)" }}>
                <ErrorBoundary renderFallback={(err) => <WidgetErrorFallback error={err} />}>
                  {renderWidget(item, contextServerId)}
                </ErrorBoundary>
              </div>
            </div>
          );
        })}
      </ResponsiveGridLayout>
    </div>
  );
}
