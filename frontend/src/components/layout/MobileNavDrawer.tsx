import { Drawer } from "vaul";
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
} from "lucide-react";
import { NavLink, useNavigate } from "react-router-dom";

// Same stable nav structure as the desktop Sidebar — labels resolved via t() so the
// drawer re-translates on language change.
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

interface Props {
  open: boolean;
  onClose: () => void;
}

/**
 * Mobile navigation drawer (Wave 7 — 04-W7-01). Below `md:` the desktop Sidebar is
 * hidden; the Header hamburger opens this vaul left-direction drawer instead. The
 * server-context selector sits at the TOP of the drawer (CONTEXT 04-W7-01 — account/
 * context at the top is the expected mobile pattern), nav items below. vaul provides
 * the ARIA focus-trap, swipe-to-dismiss, tap-outside, and ESC handling.
 */
export function MobileNavDrawer({ open, onClose }: Props) {
  const { t } = useTranslation();
  const { servers, contextServerId, setContextServer } = useServerStore();
  const navigate = useNavigate();

  async function handleSelectServer(id: string) {
    setContextServer(id);
    try {
      await put("/api/dashboard/context", { server_id: id });
    } catch {
      // silently fail if backend unavailable
    }
  }

  return (
    <Drawer.Root open={open} onOpenChange={(v) => !v && onClose()} direction="left">
      <Drawer.Portal>
        <Drawer.Overlay className="fixed inset-0 z-40 bg-black/40" />
        <Drawer.Content
          id="mobile-nav-drawer"
          className="fixed bottom-0 left-0 top-0 z-50 flex w-[280px] flex-col border-r border-border bg-sidebar outline-none"
        >
          <Drawer.Title className="sr-only">{t("nav.openMenu")}</Drawer.Title>

          {/* Logo */}
          <div className="border-b border-border px-4 py-3">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-foreground text-sm font-bold text-background">
                IL
              </div>
              <div>
                <span className="text-sm font-semibold">IPMIDeck</span>
                <span className="ml-1 text-xs text-muted-foreground">v2</span>
              </div>
            </div>
          </div>

          {/* Server context selector — at the TOP of the drawer (CONTEXT 04-W7-01). */}
          <div className="border-b border-border p-3">
            <p className="px-1 pb-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              {t("nav.selectServer")}
            </p>
            <div className="space-y-1">
              {servers.length === 0 && (
                <p className="px-1 py-1 text-xs text-muted-foreground">
                  {t("sidebar.noServersConfigured")}
                </p>
              )}
              {servers.map((server) => (
                <button
                  key={server.id}
                  onClick={() => handleSelectServer(server.id)}
                  className={cn(
                    "flex min-h-11 w-full items-center gap-2.5 rounded-md px-3 py-2 text-left transition-colors hover:bg-muted",
                    server.id === contextServerId && "bg-muted",
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
                    <p className="font-mono text-[11px] text-muted-foreground">{server.host}</p>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Platform nav */}
          <nav className="flex-1 overflow-y-auto p-2">
            <p className="px-2 pb-2 pt-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              {t("sidebar.platform")}
            </p>
            <div className="flex flex-col gap-0.5">
              {navItems.map((item) => (
                <NavLink
                  key={item.path}
                  to={item.path}
                  end={item.path === "/"}
                  onClick={onClose}
                  className={({ isActive }) =>
                    cn(
                      "flex min-h-11 items-center gap-2.5 rounded-md px-3 py-2 text-[13px] font-medium text-muted-foreground transition-colors",
                      isActive ? "bg-muted text-foreground" : "hover:bg-muted hover:text-foreground",
                    )
                  }
                >
                  <item.icon className="h-4 w-4" />
                  {t(item.labelKey)}
                </NavLink>
              ))}
            </div>

            <p className="px-2 pb-2 pt-4 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              {t("sidebar.system")}
            </p>
            <div className="flex flex-col gap-0.5">
              {systemItems.map((item) => (
                <NavLink
                  key={item.path}
                  to={item.path}
                  onClick={onClose}
                  className={({ isActive }) =>
                    cn(
                      "flex min-h-11 items-center gap-2.5 rounded-md px-3 py-2 text-[13px] font-medium text-muted-foreground transition-colors",
                      isActive ? "bg-muted text-foreground" : "hover:bg-muted hover:text-foreground",
                    )
                  }
                >
                  <item.icon className="h-4 w-4" />
                  {t(item.labelKey)}
                </NavLink>
              ))}
            </div>
          </nav>

          {/* Manage servers footer */}
          <div className="border-t border-border p-2">
            <button
              onClick={() => {
                onClose();
                navigate("/settings");
              }}
              className="flex min-h-11 w-full items-center gap-2 rounded-md px-3 py-2 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <Settings className="h-3.5 w-3.5" />
              {t("sidebar.manageServers")}
            </button>
          </div>
        </Drawer.Content>
      </Drawer.Portal>
    </Drawer.Root>
  );
}
