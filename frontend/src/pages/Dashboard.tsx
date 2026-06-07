import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Header } from "@/components/layout/Header";
import { WidgetGrid } from "@/components/dashboard/WidgetGrid";
import { WidgetCatalog } from "@/components/dashboard/WidgetCatalog";
import { useLayoutStore } from "@/stores/layout-store";
import { useServerStore } from "@/stores/server-store";
import { useRangeStore } from "@/stores/range-store";
import { useEditModeStore } from "@/stores/edit-mode-store";
import { EmptyState } from "@/components/common/EmptyState";
import { cn } from "@/lib/utils";
import { get } from "@/api/client";
import { Plus, Server, LayoutGrid, Pencil } from "lucide-react";

export default function Dashboard() {
  const { t } = useTranslation();
  const { layout, setLayout } = useLayoutStore();
  const contextServerId = useServerStore((s) => s.contextServerId);
  const servers = useServerStore((s) => s.servers);
  const range = useRangeStore((s) => s.range);
  const setRange = useRangeStore((s) => s.setRange);
  const editMode = useEditModeStore((s) => s.editMode);
  const toggleEditMode = useEditModeStore((s) => s.toggleEditMode);
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
      <Header title={t("nav.dashboard")}>
        <button
          onClick={() => setCatalogOpen(true)}
          data-tour="add-widget"
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90 transition-colors"
        >
          <Plus className="h-3.5 w-3.5" />
          {t("widget.addWidget")}
        </button>
        <button
          onClick={toggleEditMode}
          aria-label={editMode ? t("dashboard.editExitAria") : t("dashboard.editEnterAria")}
          title={editMode ? t("dashboard.editExitTitle") : t("dashboard.editEnterTitle")}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-semibold transition-colors",
            editMode
              ? "border-primary bg-primary/10 text-primary"
              : "border-border text-muted-foreground hover:bg-muted hover:text-foreground"
          )}
        >
          <Pencil className="h-3.5 w-3.5" />
          {editMode ? t("dashboard.editExit") : t("dashboard.editEnter")}
        </button>
        <div className="flex items-center gap-1 rounded-md bg-muted p-0.5">
          {(
            [
              ["dashboard.rangeLive", "live"],
              ["dashboard.range1h", "1h"],
              ["dashboard.range24h", "24h"],
              ["dashboard.range7d", "7d"],
            ] as const
          ).map(([labelKey, value]) => (
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
              {t(labelKey)}
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
            title={t("dashboard.noServersTitle")}
            description={t("dashboard.noServersDescription")}
            action={{ label: t("dashboard.addAServer"), onClick: () => navigate("/settings") }}
          />
        ) : (
          <EmptyState
            icon={LayoutGrid}
            title={t("dashboard.emptyTitle")}
            description={t("dashboard.emptyDescription")}
            action={{ label: t("dashboard.addFirstWidget"), onClick: () => setCatalogOpen(true) }}
          />
        )}
      </div>
      <WidgetCatalog open={catalogOpen} onClose={() => setCatalogOpen(false)} />
    </>
  );
}
