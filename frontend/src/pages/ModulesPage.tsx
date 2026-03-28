import { useEffect, useState } from "react";
import { Header } from "@/components/layout/Header";
import { get, put } from "@/api/client";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Thermometer, Fan, Power, List, Cpu } from "lucide-react";

interface Module {
  id: string;
  name: string;
  version: string;
  description: string;
  category: string;
  icon: string;
  enabled: boolean;
  dependencies: string[];
}

const ICONS: Record<string, React.ReactNode> = {
  thermometer: <Thermometer className="h-5 w-5" />,
  fan: <Fan className="h-5 w-5" />,
  power: <Power className="h-5 w-5" />,
  list: <List className="h-5 w-5" />,
  cpu: <Cpu className="h-5 w-5" />,
};

export default function ModulesPage() {
  const [modules, setModules] = useState<Module[]>([]);

  const loadModules = async () => {
    try {
      const data = await get<{ modules: Module[] }>("/api/admin/modules");
      setModules(data.modules);
    } catch { /* ignore */ }
  };

  useEffect(() => { loadModules(); }, []);

  const toggleModule = async (id: string, enabled: boolean) => {
    try {
      await put(`/api/admin/modules/${id}`, { enabled });
      setModules((prev) => prev.map((m) => m.id === id ? { ...m, enabled } : m));
      toast.success(`${id} ${enabled ? "enabled" : "disabled"}`);
    } catch {
      toast.error("Failed to toggle module");
    }
  };

  return (
    <>
      <Header title="Modules" />
      <div className="flex-1 overflow-auto p-6">
        <div className="mx-auto max-w-3xl">
          <p className="mb-6 text-sm text-muted-foreground">
            Enable or disable modules to customize your dashboard. Changes take effect on next restart.
          </p>
          <div className="space-y-3">
            {modules.map((mod) => (
              <div key={mod.id} className={cn("flex items-center gap-4 rounded-lg border border-border bg-card p-4 transition-opacity", !mod.enabled && "opacity-50")}>
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                  {ICONS[mod.icon] || ICONS.cpu}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold">{mod.name}</span>
                    <span className="font-mono text-[10px] text-muted-foreground">v{mod.version}</span>
                    <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{mod.category}</span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5">{mod.description}</p>
                  {mod.dependencies.length > 0 && (
                    <p className="text-[10px] text-muted-foreground mt-1">Depends on: {mod.dependencies.join(", ")}</p>
                  )}
                </div>
                <button
                  onClick={() => toggleModule(mod.id, !mod.enabled)}
                  className={cn(
                    "relative h-6 w-11 shrink-0 rounded-full transition-colors",
                    mod.enabled ? "bg-emerald-500" : "bg-muted"
                  )}
                >
                  <div className={cn(
                    "absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform",
                    mod.enabled ? "translate-x-5" : "translate-x-0.5"
                  )} />
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
