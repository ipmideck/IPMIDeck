import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Drawer } from "vaul";
import { get, put, del } from "@/api/client";
import { useLayoutStore, type WidgetLayout } from "@/stores/layout-store";
import { useServerStore } from "@/stores/server-store";
import { useBackendOnline } from "@/stores/connection-store";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { SUPPORTED_WIDGET_IDS, WIDGET_VIEWS } from "@/modules/registry";
import { cn } from "@/lib/utils";
import { X, LayoutGrid, RotateCcw, AlertTriangle } from "lucide-react";
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
  const { t } = useTranslation();
  const [widgets, setWidgets] = useState<CatalogWidget[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedServer, setSelectedServer] = useState<string>("");
  const [confirmingReset, setConfirmingReset] = useState(false);
  const [resetting, setResetting] = useState(false);
  // When set, the catalog renders an inline view picker for this multi-view
  // widget instead of immediately adding it on click. Cleared on close,
  // selection, or a second click on the same widget.
  const [pickingFor, setPickingFor] = useState<CatalogWidget | null>(null);
  const addWidget = useLayoutStore((s) => s.addWidget);
  const setLayout = useLayoutStore((s) => s.setLayout);
  const layout = useLayoutStore((s) => s.layout);
  const servers = useServerStore((s) => s.servers);
  const contextServerId = useServerStore((s) => s.contextServerId);
  const online = useBackendOnline();
  // Below md: the catalog opens as a full-screen vaul bottom sheet (Wave 7 — 04-W7-01).
  const isMobile = useMediaQuery("(max-width: 767px)");

  useEffect(() => {
    if (!open) {
      setConfirmingReset(false); // never reopen mid-confirmation
      setPickingFor(null); // never reopen mid-view-pick
      return;
    }
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

  function handleAddWithView(widget: CatalogWidget, configPatch?: Record<string, unknown>) {
    const id = `${widget.widget_id}-${Date.now()}`;
    const newWidget: WidgetLayout = {
      i: id,
      widget_id: widget.widget_id,
      module_id: widget.module_id,
      server_id: selectedServer || contextServerId || undefined,
      x: 0,
      y: Infinity,
      w: widget.default_w,
      h: widget.default_h,
      config: configPatch && Object.keys(configPatch).length > 0 ? configPatch : undefined,
    };
    addWidget(newWidget);

    // Save layout
    const updatedLayout = [...layout, newWidget];
    put("/api/dashboard/layout", { layout: updatedLayout }).catch(() => {});

    toast.success(t("widget.added"));
    setPickingFor(null);
    onClose();
  }

  function handleAdd(widget: CatalogWidget) {
    handleAddWithView(widget); // no view = no config.view written (single-view widgets)
  }

  function onClickWidget(widget: CatalogWidget) {
    const views = WIDGET_VIEWS[widget.widget_id];
    if (!views || views.length <= 1) {
      handleAdd(widget); // immediate add (existing behavior)
      return;
    }
    // Multi-view widget — toggle the inline picker for this card
    setPickingFor((cur) => (cur?.widget_id === widget.widget_id ? null : widget));
  }

  async function handleReset() {
    setResetting(true);
    try {
      // Backend DELETE clears the saved layout and returns the default set.
      const res = await del<{ success: boolean; layout: WidgetLayout[] }>("/api/dashboard/layout");
      setLayout(res.layout || []);
      toast.success(t("widget.resetLayoutDone"));
      setConfirmingReset(false);
      onClose();
    } catch {
      toast.error(t("widget.resetLayoutFailed"));
    } finally {
      setResetting(false);
    }
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

  // Catalog header chrome — title + close + reset-layout confirm + server picker.
  const headerInner = (
    <>
      <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">{t("widget.catalogTitle")}</h2>
            <button
              onClick={onClose}
              className="rounded p-1 hover:bg-muted transition-colors"
            >
              <X className="h-4 w-4 text-muted-foreground" />
            </button>
          </div>

          {/* Reset layout — at the top of the menu, with a confirm CTA before destroying the layout */}
          {!confirmingReset ? (
            <button
              onClick={() => setConfirmingReset(true)}
              disabled={!online}
              title={!online ? t("header.backendDisconnected") : undefined}
              className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground transition-colors disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              {t("widget.resetLayout")}
            </button>
          ) : (
            <div className="mt-3 rounded-md border border-danger/30 bg-danger/5 p-3">
              <div className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" />
                <p className="text-xs text-muted-foreground">
                  {t("widget.resetLayoutConfirm")}
                </p>
              </div>
              <div className="mt-3 flex gap-2">
                <button
                  onClick={() => setConfirmingReset(false)}
                  disabled={resetting}
                  className="flex-1 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50"
                >
                  {t("widget.cancel")}
                </button>
                <button
                  onClick={handleReset}
                  disabled={resetting || !online}
                  title={!online ? t("header.backendDisconnected") : undefined}
                  className="flex-1 rounded-md bg-danger px-3 py-1.5 text-xs font-semibold text-white hover:bg-danger/90 transition-colors disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {resetting ? t("widget.resetting") : t("widget.reset")}
                </button>
              </div>
            </div>
          )}

          {servers.length > 1 && (
            <select
              aria-label={t("widget.assignToServer")}
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
    </>
  );

  // Catalog body — loading spinner / empty state / grouped widget cards.
  const contentInner = (
    <>
          {loading && (
            <div className="flex items-center justify-center py-12">
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
            </div>
          )}

          {!loading && widgets.length === 0 && (
            <p className="py-8 text-center text-xs text-muted-foreground">
              {t("widget.noWidgets")}
            </p>
          )}

          {!loading &&
            Object.entries(grouped).map(([moduleName, moduleWidgets]) => (
              <div key={moduleName} className="mb-5">
                <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  {moduleName}
                </h3>
                <div className="space-y-2">
                  {moduleWidgets.map((w) => {
                    const views = WIDGET_VIEWS[w.widget_id];
                    const isPicking = pickingFor?.widget_id === w.widget_id;
                    return (
                      <div key={w.widget_id}>
                        <button
                          onClick={() => onClickWidget(w)}
                          disabled={!online}
                          title={!online ? t("header.backendDisconnected") : undefined}
                          className={cn(
                            "flex w-full items-start gap-3 rounded-lg border p-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                            isPicking
                              ? "border-primary bg-primary/5"
                              : "border-border hover:bg-muted/50"
                          )}
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
                        {isPicking && views && (
                          <div className="mt-2 rounded-md border border-border bg-muted/30 p-2">
                            <p className="mb-2 text-[10px] uppercase tracking-wider text-muted-foreground">
                              {t("widget.chooseView")}
                            </p>
                            <div className="grid grid-cols-2 gap-2">
                              {views.map((opt) => {
                                const Icon = opt.icon;
                                return (
                                  <button
                                    key={opt.value}
                                    onClick={() =>
                                      handleAddWithView(w, opt.config ?? { view: opt.value })
                                    }
                                    className="flex flex-col items-start gap-1 rounded-md border border-border bg-card p-2 text-left hover:bg-muted/50 transition-colors"
                                  >
                                    <div className="flex items-center gap-1.5">
                                      {Icon && <Icon className="h-3.5 w-3.5 text-muted-foreground" />}
                                      <span className="text-xs font-semibold">{t(opt.labelKey)}</span>
                                    </div>
                                    <span className="text-[10px] leading-snug text-muted-foreground line-clamp-2">
                                      {t(opt.descKey)}
                                    </span>
                                  </button>
                                );
                              })}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
    </>
  );

  // Mobile (< md): full-screen vaul bottom sheet with swipe-to-dismiss.
  if (isMobile) {
    return (
      <Drawer.Root open={open} onOpenChange={(v) => !v && onClose()}>
        <Drawer.Portal>
          <Drawer.Overlay className="fixed inset-0 z-40 bg-black/40" />
          <Drawer.Content className="fixed bottom-0 inset-x-0 z-50 flex max-h-[90vh] flex-col rounded-t-2xl border-t border-border bg-card outline-none">
            <Drawer.Title className="sr-only">{t("widget.catalogTitle")}</Drawer.Title>
            {/* Grab handle */}
            <div className="mx-auto mt-3 h-1.5 w-12 shrink-0 rounded-full bg-muted-foreground/30" />
            <div className="shrink-0 border-b border-border px-4 py-3">{headerInner}</div>
            <div className="flex-1 overflow-auto p-4">{contentInner}</div>
          </Drawer.Content>
        </Drawer.Portal>
      </Drawer.Root>
    );
  }

  // Desktop (>= md): existing right-side slide-in drawer.
  return (
    <>
      {/* Backdrop */}
      {open && <div className="fixed inset-0 z-40 bg-black/40" onClick={onClose} />}

      {/* Panel */}
      <div
        className={cn(
          "fixed right-0 top-0 z-50 flex h-full w-80 flex-col border-l border-border bg-card shadow-xl transition-transform duration-200",
          open ? "translate-x-0" : "translate-x-full"
        )}
      >
        <div className="border-b border-border px-4 py-3">{headerInner}</div>
        <div className="flex-1 overflow-auto p-4">{contentInner}</div>
      </div>
    </>
  );
}
