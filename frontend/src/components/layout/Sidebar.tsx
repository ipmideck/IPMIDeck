import { cn } from "@/lib/utils";
import { useServerStore } from "@/stores/server-store";
import {
  LayoutDashboard,
  Fan,
  List,
  Cpu,
  Package,
  Settings,
  ChevronRight,
} from "lucide-react";
import { NavLink } from "react-router-dom";

const navItems = [
  { label: "Dashboard", path: "/", icon: LayoutDashboard },
  { label: "FanPilot", path: "/fanpilot", icon: Fan },
  { label: "Event Log", path: "/sel", icon: List },
  { label: "Hardware", path: "/fru", icon: Cpu },
];

const systemItems = [
  { label: "Modules", path: "/modules", icon: Package },
  { label: "Settings", path: "/settings", icon: Settings },
];

export function Sidebar() {
  const { servers, contextServerId, setContextServer } = useServerStore();
  const contextServer = servers.find((s) => s.id === contextServerId);

  return (
    <aside className="flex h-screen w-[var(--sidebar-width)] flex-col border-r border-border bg-sidebar sticky top-0 shrink-0">
      {/* Logo */}
      <div className="border-b border-border px-4 py-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-foreground text-background font-bold text-sm">
            IL
          </div>
          <div>
            <span className="text-sm font-semibold">IPMILink</span>
            <span className="ml-1 text-xs text-muted-foreground">v2</span>
          </div>
        </div>
      </div>

      {/* Platform nav */}
      <div className="px-2 pt-3">
        <p className="px-2 pb-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Platform
        </p>
        <nav className="flex flex-col gap-0.5">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === "/"}
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
              {item.label}
            </NavLink>
          ))}
        </nav>
      </div>

      {/* System nav */}
      <div className="px-2 pt-4">
        <p className="px-2 pb-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          System
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
              {item.label}
            </NavLink>
          ))}
        </nav>
      </div>

      {/* Server selector (footer) */}
      <div className="mt-auto border-t border-border p-3">
        <button className="flex w-full items-center gap-2.5 rounded-md bg-muted px-3 py-2 text-left transition-colors hover:bg-accent">
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
              {contextServer?.name || "No server"}
            </p>
            <p className="font-mono text-[11px] text-muted-foreground">
              {contextServer?.host || "—"}
            </p>
          </div>
          <ChevronRight className="h-3 w-3 text-muted-foreground" />
        </button>
      </div>
    </aside>
  );
}
