import { Command } from "cmdk";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useServerStore } from "@/stores/server-store";
import { put } from "@/api/client";
import {
  LayoutDashboard,
  Fan,
  List,
  Cpu,
  Package,
  Settings,
  Server,
  Power,
  PowerOff,
  Volume2,
} from "lucide-react";

const pages = [
  { label: "Dashboard", path: "/", icon: LayoutDashboard },
  { label: "FanPilot", path: "/fanpilot", icon: Fan },
  { label: "Event Log", path: "/sel", icon: List },
  { label: "Hardware", path: "/fru", icon: Cpu },
  { label: "Modules", path: "/modules", icon: Package },
  { label: "Settings", path: "/settings", icon: Settings },
];

const actions = [
  { label: "Power On", keywords: ["power", "start", "boot"], icon: Power },
  { label: "Power Off", keywords: ["power", "shutdown", "stop"], icon: PowerOff },
  { label: "Power Cycle", keywords: ["restart", "reboot", "cycle"], icon: Power },
  { label: "Switch to Silent", keywords: ["fan", "quiet", "silent", "profile"], icon: Volume2 },
  { label: "Switch to Balanced", keywords: ["fan", "balanced", "profile"], icon: Volume2 },
  { label: "Switch to Performance", keywords: ["fan", "performance", "loud", "profile"], icon: Volume2 },
];

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { servers, setContextServer } = useServerStore();

  // Listen for Cmd+K / Ctrl+K
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  async function handleSelectServer(id: string) {
    setContextServer(id);
    setOpen(false);
    try {
      await put("/api/dashboard/context", { server_id: id });
    } catch {
      // silently fail
    }
  }

  function handleSelectPage(path: string) {
    navigate(path);
    setOpen(false);
  }

  function handleSelectAction(_label: string) {
    // Actions are placeholders for now — close palette
    setOpen(false);
  }

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      label="Command palette"
      loop
      overlayClassName="fixed inset-0 bg-black/50 z-50"
      contentClassName="fixed top-[20%] left-1/2 -translate-x-1/2 z-50 w-full max-w-lg"
    >
      <div className="rounded-xl border border-border bg-popover text-popover-foreground shadow-2xl overflow-hidden">
        <Command.Input
          placeholder="Type a command or search..."
          className="w-full border-b border-border bg-transparent px-4 py-3 text-sm outline-none placeholder:text-muted-foreground"
        />
        <Command.List className="max-h-80 overflow-y-auto p-2">
          <Command.Empty className="px-4 py-6 text-center text-sm text-muted-foreground">
            No results found.
          </Command.Empty>

          {/* Servers */}
          {servers.length > 0 && (
            <Command.Group
              heading="Servers"
              className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-muted-foreground"
            >
              {servers.map((server) => (
                <Command.Item
                  key={server.id}
                  value={`server ${server.name} ${server.host}`}
                  onSelect={() => handleSelectServer(server.id)}
                  className="flex items-center gap-3 rounded-md px-2 py-2 text-sm cursor-pointer aria-selected:bg-accent aria-selected:text-accent-foreground"
                >
                  <Server className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="flex items-center gap-2 min-w-0 flex-1">
                    <div
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{
                        backgroundColor: server.is_online
                          ? "var(--color-success)"
                          : "var(--color-danger)",
                      }}
                    />
                    <span className="truncate">{server.name}</span>
                    <span className="font-mono text-xs text-muted-foreground">{server.host}</span>
                  </div>
                </Command.Item>
              ))}
            </Command.Group>
          )}

          {/* Pages */}
          <Command.Group
            heading="Pages"
            className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-muted-foreground"
          >
            {pages.map((page) => (
              <Command.Item
                key={page.path}
                value={`page ${page.label}`}
                onSelect={() => handleSelectPage(page.path)}
                className="flex items-center gap-3 rounded-md px-2 py-2 text-sm cursor-pointer aria-selected:bg-accent aria-selected:text-accent-foreground"
              >
                <page.icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span>{page.label}</span>
              </Command.Item>
            ))}
          </Command.Group>

          {/* Actions */}
          <Command.Group
            heading="Actions"
            className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-muted-foreground"
          >
            {actions.map((action) => (
              <Command.Item
                key={action.label}
                value={`action ${action.label}`}
                keywords={action.keywords}
                onSelect={() => handleSelectAction(action.label)}
                className="flex items-center gap-3 rounded-md px-2 py-2 text-sm cursor-pointer aria-selected:bg-accent aria-selected:text-accent-foreground"
              >
                <action.icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span>{action.label}</span>
              </Command.Item>
            ))}
          </Command.Group>
        </Command.List>
      </div>
    </Command.Dialog>
  );
}
