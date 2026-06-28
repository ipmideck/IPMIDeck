import { useCallback, useRef, useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { ResponsiveGridLayout } from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import { useLayoutStore, type WidgetLayout } from "@/stores/layout-store";
import { useServerStore, type Server } from "@/stores/server-store";
import { useModuleStore } from "@/stores/module-store";
import { useEditModeStore } from "@/stores/edit-mode-store";
import { useWidgetRender, getWidgetTitle } from "@/modules/registry";
import { ErrorBoundary, WidgetErrorFallback } from "@/components/ErrorBoundary";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { X, ChevronDown } from "lucide-react";
import { put } from "@/api/client";
import { cn } from "@/lib/utils";

export function WidgetGrid() {
  const { t } = useTranslation();
  const { layout, removeWidget, updateLayout, setWidgetServer, updateWidgetConfig } = useLayoutStore();
  const contextServerId = useServerStore((s) => s.contextServerId);
  const servers = useServerStore((s) => s.servers);
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(1000);
  const [openTagId, setOpenTagId] = useState<string | null>(null);
  const showIdentity = servers.length > 1;
  const editMode = useEditModeStore((s) => s.editMode);
  const setEditMode = useEditModeStore((s) => s.setEditMode);
  // Below md: (< 768px) the grid stacks to a single column and resize is disabled;
  // a 600ms long-press on a widget body enters edit mode (Wave 7 — 04-W7-01).
  const isMobile = useMediaQuery("(max-width: 767px)");

  // Hydrate the module-enabled map once on mount so useWidgetRender can gate
  // disabled-module widgets (MOD-01 D-14). Done here, not in Dashboard.tsx.
  useEffect(() => {
    useModuleStore.getState().loadModules();
  }, []);

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

  const handleConfigChange = useCallback((id: string, config: Record<string, unknown>) => {
    updateWidgetConfig(id, config);
    const merged = layout.map((w) =>
      w.i === id ? { ...w, config: { ...(w.config ?? {}), ...config } } : w
    );
    put("/api/dashboard/layout", { layout: merged }).catch(() => {});
  }, [layout, updateWidgetConfig]);

  const handleLayoutChange = useCallback((newLayout: readonly any[]) => {
    // Only the canonical desktop (lg) layout is persisted. Below the lg breakpoint the grid
    // shows a generated single-column stack (view-only); persisting that would overwrite the
    // user's saved arrangement, which is exactly the "resize scrambles everything" bug.
    if (width < 1024) return;
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
  }, [layout, updateLayout, width]);

  const handleSwitchServer = useCallback((itemId: string, newServerId: string) => {
    setWidgetServer(itemId, newServerId);
    const merged = layout.map((w) =>
      w.i === itemId ? { ...w, server_id: newServerId } : w
    );
    put("/api/dashboard/layout", { layout: merged }).catch(() => {});
  }, [layout, setWidgetServer]);

  if (!contextServerId) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
        {t("widget.noServerConfigured")}
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

  // Narrow-screen layout: a predictable single-column stack in reading order (top-to-bottom,
  // then left-to-right), heights preserved. Avoids react-grid-layout's auto-generated reflow,
  // which left gaps/overlaps ("sminchiato"). View-only — never persisted (see handleLayoutChange).
  let stackY = 0;
  const stackedLayout = [...layout]
    .sort((a, b) => a.y - b.y || a.x - b.x)
    .map((item) => {
      const l = { i: item.i, x: 0, y: stackY, w: 1, h: item.h, minW: 1, minH: 1 };
      stackY += item.h;
      return l;
    });

  return (
    <div ref={containerRef}>
      <ResponsiveGridLayout
        className="react-grid-layout"
        width={width}
        layouts={{ lg: gridLayout, md: gridLayout, sm: stackedLayout, xs: stackedLayout, xxs: stackedLayout }}
        breakpoints={{ lg: 1024, md: 768, sm: 414, xs: 375, xxs: 320 }}
        cols={{ lg: 6, md: 6, sm: 1, xs: 1, xxs: 1 }}
        rowHeight={120}
        margin={[16, 16] as const}
        containerPadding={[0, 0] as const}
        dragConfig={{ enabled: editMode, handle: ".widget-drag-handle" }}
        resizeConfig={{ enabled: !isMobile && editMode }}
        onLayoutChange={handleLayoutChange}
      >
        {layout.map((item) => {
          const widgetServerId = item.server_id || contextServerId;
          const widgetServer = servers.find((s) => s.id === widgetServerId);
          return (
            <div key={item.i}>
              <WidgetCard
                item={item}
                contextServerId={contextServerId}
                servers={servers}
                accentServer={showIdentity ? widgetServer : undefined}
                editMode={editMode}
                isMobile={isMobile}
                onLongPress={() => setEditMode(true)}
                openTagId={openTagId}
                setOpenTagId={setOpenTagId}
                onRemove={handleRemove}
                onConfigChange={handleConfigChange}
                onSwitchServer={handleSwitchServer}
              />
            </div>
          );
        })}
      </ResponsiveGridLayout>
    </div>
  );
}

/**
 * Per-widget card. Factored into its own component so the useWidgetRender hook
 * is called at the top level (React hook rules) — calling it inside the
 * layout.map() callback would violate them.
 */
function WidgetCard({
  item,
  contextServerId,
  servers,
  accentServer,
  editMode,
  isMobile,
  onLongPress,
  openTagId,
  setOpenTagId,
  onRemove,
  onConfigChange,
  onSwitchServer,
}: {
  item: WidgetLayout;
  contextServerId: string;
  servers: Server[];
  accentServer: Server | undefined;
  editMode: boolean;
  isMobile: boolean;
  onLongPress: () => void;
  openTagId: string | null;
  setOpenTagId: (id: string | null) => void;
  onRemove: (id: string) => void;
  onConfigChange: (id: string, config: Record<string, unknown>) => void;
  onSwitchServer: (itemId: string, serverId: string) => void;
}) {
  const { t } = useTranslation();
  const { body, headerActions } = useWidgetRender(
    item,
    contextServerId,
    (config) => onConfigChange(item.i, config)
  );
  const accent = !!accentServer;

  // Long-press (600ms) to enter edit mode — mobile only, when not already editing.
  // Attached to the card wrapper, NOT the drag handle (the handle owns its own touch
  // behaviour once edit mode is on). Any move/end/cancel clears the pending timer.
  const touchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearTouchTimer = useCallback(() => {
    if (touchTimer.current) {
      clearTimeout(touchTimer.current);
      touchTimer.current = null;
    }
  }, []);
  const onTouchStart = useCallback(() => {
    if (!isMobile || editMode) return;
    clearTouchTimer();
    touchTimer.current = setTimeout(() => onLongPress(), 600);
  }, [isMobile, editMode, onLongPress, clearTouchTimer]);

  return (
    <div
      className={cn(
        // D-06: lift the card off the canvas. The card surface (--color-card) already
        // sits above the page canvas (--color-background); a real shadow + the tinted
        // header band below give the elevation the eye needs to read each tile as a
        // distinct layer from ~2m, instead of separation riding on a 1px hairline.
        "group relative h-full rounded-lg shadow-md overflow-hidden border transition-shadow hover:shadow-lg",
        editMode ? "border-dashed border-primary/50 bg-card/95" : "border-border bg-card",
        accent && "border-l-[3px]"
      )}
      style={accent && accentServer ? { borderLeftColor: accentServer.color } : undefined}
      onTouchStart={onTouchStart}
      onTouchMove={clearTouchTimer}
      onTouchEnd={clearTouchTimer}
      onTouchCancel={clearTouchTimer}
    >
      <div
        className={cn(
          // D-06: a faintly tinted header band (--color-muted = blueprint surface-2)
          // reads as a third layer above the card body, so the title row is a real
          // header instead of dissolving into the tile.
          "widget-drag-handle flex items-center justify-between border-b border-border bg-muted/40 px-3 py-2",
          editMode ? "cursor-grab active:cursor-grabbing" : "cursor-default"
        )}
        // touch-action: none ONLY on the handle, ONLY in edit mode (RESEARCH Pitfall 6).
        // Outside edit mode the user must be able to scroll the page past the header.
        style={editMode ? { touchAction: "none" } : undefined}
      >
        {/* D-06: brighter, slightly larger title in uppercase tracking so widget
            identity is scannable at a glance — was text-[11px] muted (too quiet). */}
        <span className="text-[11px] font-semibold uppercase tracking-wide text-foreground/80 select-none">
          {getWidgetTitle(item, t)}
        </span>
        <div className="flex items-center gap-1">
          {headerActions && (
            <span
              onMouseDown={(e) => e.stopPropagation()}
              className="flex items-center gap-0.5"
            >
              {headerActions}
            </span>
          )}
          {accent && accentServer && (
            <div className="relative">
              <button
                aria-label={t("widget.switchServer")}
                onMouseDown={(e) => e.stopPropagation()}
                onClick={() => setOpenTagId(openTagId === item.i ? null : item.i)}
                className="flex items-center gap-1 text-[11px] font-semibold text-muted-foreground"
              >
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ background: accentServer.color }}
                />
                {accentServer.name}
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
                          onSwitchServer(item.i, s.id);
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
          {editMode && (
            <button
              onClick={() => onRemove(item.i)}
              className="rounded p-0.5 hover:bg-muted"
            >
              <X className="h-3 w-3 text-muted-foreground" />
            </button>
          )}
        </div>
      </div>
      <div className="p-3" style={{ height: "calc(100% - 33px)" }}>
        <ErrorBoundary renderFallback={(err) => <WidgetErrorFallback error={err} />}>
          {body}
        </ErrorBoundary>
      </div>
    </div>
  );
}
