import { useEffect, useState } from "react";
import { Header } from "@/components/layout/Header";
import { useServerStore, type Server } from "@/stores/server-store";
import { useThemeStore } from "@/stores/theme-store";
import { get, post, put, del } from "@/api/client";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Plus, Trash2, TestTube, ExternalLink, Heart, Code2, Moon, Sun, Monitor } from "lucide-react";

export default function SettingsPage() {
  const { servers, setServers } = useServerStore();
  const { theme, setTheme } = useThemeStore();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", host: "", username: "", password: "", vendor: "dell" });
  const [testing, setTesting] = useState<string | null>(null);

  const loadServers = async () => {
    try {
      const data = await get<{ servers: Server[] }>("/api/servers");
      setServers(data.servers);
    } catch { /* ignore */ }
  };

  useEffect(() => { loadServers(); }, []);

  const addServer = async () => {
    if (!form.host || !form.username || !form.password) {
      toast.error("Host, username, and password are required");
      return;
    }
    try {
      const res = await post<{ success: boolean; server_id: string }>("/api/servers", {
        name: form.name || form.host,
        description: form.description,
        host: form.host,
        username: form.username,
        password: form.password,
        vendor: form.vendor,
      });
      if (res.success) {
        toast.success("Server added");
        setForm({ name: "", description: "", host: "", username: "", password: "", vendor: "dell" });
        setShowForm(false);
        await loadServers();
      }
    } catch {
      toast.error("Failed to add server");
    }
  };

  const deleteServer = async (id: string) => {
    try {
      await del(`/api/servers/${id}`);
      toast.success("Server removed");
      await loadServers();
    } catch {
      toast.error("Failed to delete server");
    }
  };

  const testServer = async (id: string) => {
    setTesting(id);
    try {
      const res = await post<{ success: boolean; power_status?: string; error?: string }>(`/api/servers/${id}/test`);
      if (res.success) {
        toast.success(`Connection OK — power ${res.power_status}`);
        await loadServers();
      } else {
        toast.error(res.error || "Connection failed");
      }
    } catch {
      toast.error("Connection failed");
    } finally {
      setTesting(null);
    }
  };

  return (
    <>
      <Header title="Settings" />
      <div className="flex-1 overflow-auto p-6">
        <div className="mx-auto max-w-2xl space-y-6">

          {/* Servers */}
          <div className="rounded-lg border border-border bg-card p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Servers</h2>
              <button onClick={() => setShowForm(!showForm)} className="flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-xs font-medium hover:bg-muted">
                <Plus className="h-3 w-3" /> Add
              </button>
            </div>

            {showForm && (
              <div className="mb-4 space-y-3 rounded-md border border-border bg-muted/50 p-4">
                <div className="grid grid-cols-2 gap-3">
                  <input placeholder="Name (e.g., Dell R720)" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm" />
                  <input placeholder="Description (optional)" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm" />
                  <input placeholder="BMC IP (e.g., 192.0.2.10)" value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm" />
                  <select value={form.vendor} onChange={(e) => setForm({ ...form, vendor: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm">
                    <option value="dell">Dell</option>
                    <option value="supermicro">Supermicro</option>
                    <option value="hpe">HPE</option>
                    <option value="generic">Generic</option>
                  </select>
                  <input placeholder="IPMI Username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm" />
                  <input type="password" placeholder="IPMI Password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm font-mono" />
                </div>
                <div className="flex justify-end gap-2">
                  <button onClick={() => setShowForm(false)} className="rounded-md px-3 py-1.5 text-xs hover:bg-muted">Cancel</button>
                  <button onClick={addServer} className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground">Add Server</button>
                </div>
              </div>
            )}

            {servers.length === 0 ? (
              <p className="text-sm text-muted-foreground">No servers configured. Add one to start monitoring.</p>
            ) : (
              <div className="space-y-2">
                {servers.map((s) => (
                  <div key={s.id} className="flex items-center gap-3 rounded-md border border-border p-3">
                    <div className={`h-2.5 w-2.5 shrink-0 rounded-full ${s.is_online ? "bg-emerald-500" : "bg-red-500"}`} />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium">{s.name}</div>
                      <div className="font-mono text-xs text-muted-foreground">{s.host}</div>
                    </div>
                    <div className="flex gap-1">
                      <button onClick={() => testServer(s.id)} disabled={testing === s.id} className="rounded-md border border-border p-1.5 hover:bg-muted">
                        <TestTube className={cn("h-3.5 w-3.5", testing === s.id && "animate-spin")} />
                      </button>
                      <button onClick={() => deleteServer(s.id)} className="rounded-md border border-border p-1.5 hover:bg-muted text-red-500">
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Appearance */}
          <div className="rounded-lg border border-border bg-card p-5">
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-muted-foreground">Appearance</h2>
            <div className="flex gap-2">
              {[
                { value: "dark" as const, label: "Dark", icon: Moon },
                { value: "light" as const, label: "Light", icon: Sun },
                { value: "system" as const, label: "System", icon: Monitor },
              ].map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setTheme(opt.value)}
                  className={cn(
                    "flex items-center gap-2 rounded-md border px-3 py-2 text-xs font-medium transition-colors",
                    theme === opt.value ? "border-foreground bg-muted" : "border-border hover:bg-muted"
                  )}
                >
                  <opt.icon className="h-3.5 w-3.5" />
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* About */}
          <div className="rounded-lg border border-border bg-card p-5">
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-muted-foreground">About IPMILink</h2>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Version</span>
                <span className="font-mono text-sm">2.0.0-alpha.1</span>
              </div>
              <div className="border-t border-border" />
              <div className="flex items-start gap-3 pt-1">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-muted text-sm font-semibold">LT</div>
                <div>
                  <p className="text-sm font-medium">Luigi Tanzillo</p>
                  <p className="text-xs text-muted-foreground">Creator & Developer</p>
                  <a href="https://github.com/dev-luigi" target="_blank" rel="noopener noreferrer" className="mt-1.5 inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground">
                    <Code2 className="h-3 w-3" /> dev-luigi <ExternalLink className="h-2.5 w-2.5" />
                  </a>
                </div>
              </div>
              <div className="border-t border-border" />
              <p className="flex items-center gap-1 text-xs text-muted-foreground">
                Made with <Heart className="h-3 w-3 text-red-500" /> for the homelab community
              </p>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
