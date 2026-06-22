import { cn } from "@/lib/utils";
import { useTranslation } from "react-i18next";
import { useServerStore } from "@/stores/server-store";
import { put } from "@/api/client";
import {
  LayoutDashboard,
  Fan,
  List,
  Cpu,
  Package,
  Settings,
  ChevronUp,
  ChevronRight,
} from "lucide-react";
import { NavLink, useNavigate } from "react-router-dom";
import { useState, useRef, useEffect } from "react";

// Only stable paths + i18n keys live at module load; labels are resolved via t() in
// render so the nav re-translates on language change.
const navItems = [
  { labelKey: "nav.dashboard", path: "/", icon: LayoutDashboard },
  { labelKey: "nav.fanpilot", path: "/fanpilot", icon: Fan },
  { labelKey: "nav.sel", path: "/sel", icon: List },
  { labelKey: "nav.fru", path: "/fru", icon: Cpu },
];

const systemItems = [
  { labelKey: "nav.modules", path: "/modules", icon: Package },
  { labelKey: "nav.settings", path: "/settings", icon: Settings },
];

export function Sidebar() {
  const { t } = useTranslation();
  const { servers, contextServerId, setContextServer } = useServerStore();
  const contextServer = servers.find((s) => s.id === contextServerId);
  const [selectorOpen, setSelectorOpen] = useState(false);
  const selectorRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  // Close dropdown on click outside
  useEffect(() => {
    if (!selectorOpen) return;
    function handleClick(e: MouseEvent) {
      if (selectorRef.current && !selectorRef.current.contains(e.target as Node)) {
        setSelectorOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [selectorOpen]);

  async function handleSelectServer(id: string) {
    setContextServer(id);
    setSelectorOpen(false);
    try {
      await put("/api/dashboard/context", { server_id: id });
    } catch {
      // silently fail if backend unavailable
    }
  }

  return (
    <aside className="hidden md:flex h-full w-[var(--sidebar-width)] flex-col border-r border-border bg-sidebar sticky top-0 shrink-0">
      {/* Logo */}
      <div className="border-b border-border px-4 py-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-foreground text-background font-bold text-sm">
            ID
          </div>
          <div>
            <span className="text-sm font-semibold">IPMIDeck</span>
            <span className="ml-1 text-xs text-muted-foreground">v2</span>
          </div>
        </div>
      </div>

      {/* Platform nav */}
      <div className="px-2 pt-3">
        <p className="px-2 pb-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          {t("sidebar.platform")}
        </p>
        <nav className="flex flex-col gap-0.5" data-tour="sidebar-nav">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === "/"}
              data-tour={item.path === "/fanpilot" ? "nav-fanpilot" : undefined}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] font-medium text-muted-foreground transition-colors",
                  isActive
                    ? "bg-muted text-foreground"
                    : "hover:bg-muted hover:text-foreground"
                )
              }
            >
              <item.icon className="h-4 w-4" />
              {t(item.labelKey)}
            </NavLink>
          ))}
        </nav>
      </div>

      {/* System nav */}
      <div className="px-2 pt-4">
        <p className="px-2 pb-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          {t("sidebar.system")}
        </p>
        <nav className="flex flex-col gap-0.5">
          {systemItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] font-medium text-muted-foreground transition-colors",
                  isActive
                    ? "bg-muted text-foreground"
                    : "hover:bg-muted hover:text-foreground"
                )
              }
            >
              <item.icon className="h-4 w-4" />
              {t(item.labelKey)}
            </NavLink>
          ))}
        </nav>
      </div>

      {/* Server selector (footer) */}
      <div className="mt-auto border-t border-border p-3 relative" ref={selectorRef}>
        {/* Dropdown popover — positioned above button */}
        {selectorOpen && (
          <div className="absolute bottom-full left-3 right-3 mb-2 rounded-lg border border-border bg-popover text-popover-foreground shadow-lg z-50">
            <div className="max-h-60 overflow-y-auto py-1">
              {servers.length === 0 && (
                <p className="px-3 py-2 text-xs text-muted-foreground">{t("sidebar.noServersConfigured")}</p>
              )}
              {servers.map((server) => (
                <button
                  key={server.id}
                  onClick={() => handleSelectServer(server.id)}
                  className={cn(
                    "flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-accent",
                    server.id === contextServerId && "bg-muted"
                  )}
                >
                  <div
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{
                      backgroundColor: server.is_online
                        ? "var(--color-success)"
                        : "var(--color-danger)",
                    }}
                  />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium">{server.name}</p>
                    <p className="font-mono text-[11px] text-muted-foreground">
                      {server.host}
                    </p>
                  </div>
                </button>
              ))}
            </div>
            <div className="border-t border-border">
              <button
                onClick={() => {
                  setSelectorOpen(false);
                  navigate("/settings");
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              >
                <Settings className="h-3 w-3" />
                {t("sidebar.manageServers")}
              </button>
            </div>
          </div>
        )}

        <button
          onClick={() => setSelectorOpen((prev) => !prev)}
          data-tour="server-switcher"
          className="flex w-full items-center gap-2.5 rounded-md bg-muted px-3 py-2 text-left transition-colors hover:bg-accent"
        >
          <div
            className="h-2 w-2 shrink-0 rounded-full"
            style={{
              backgroundColor: contextServer?.is_online
                ? "var(--color-success)"
                : "var(--color-danger)",
            }}
          />
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-medium">
              {contextServer?.name || t("sidebar.noServer")}
            </p>
            <p className="font-mono text-[11px] text-muted-foreground">
              {contextServer?.host || "\u2014"}
            </p>
          </div>
          {selectorOpen ? (
            <ChevronUp className="h-3 w-3 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3 w-3 text-muted-foreground" />
          )}
        </button>
      </div>
    </aside>
  );
}
