import { useEffect, useState } from "react";
import { Header } from "@/components/layout/Header";
import { useServerStore, type Server } from "@/stores/server-store";
import { useThemeStore } from "@/stores/theme-store";
import { useAuthStore } from "@/stores/auth-store";
import { get, post, put, del } from "@/api/client";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Plus, Trash2, TestTube, Pencil, ExternalLink, Heart, Code2, Moon, Sun, Monitor, Server as ServerIcon, ShieldCheck, ShieldOff } from "lucide-react";
import { EmptyState } from "@/components/common/EmptyState";

export default function SettingsPage() {
  const { servers, setServers } = useServerStore();
  const { theme, setTheme } = useThemeStore();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", host: "", username: "", password: "", vendor: "dell" });
  const [testing, setTesting] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState({ name: "", description: "", host: "", username: "", password: "", vendor: "dell" });

  // Security card (D-08..D-10): enable -> /configure (fresh creds), disable -> /toggle {enabled:false}.
  const authEnabled = useAuthStore((s) => s.authEnabled);
  const [secUsername, setSecUsername] = useState("");
  const [secPassword, setSecPassword] = useState("");
  const [secBusy, setSecBusy] = useState(false);

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

  const startEdit = (s: Server) => {
    // Pre-fill from the server; credentials stay blank (blank = keep current).
    // Only one edit open at a time, and opening edit closes the top add form.
    setEditForm({
      name: s.name,
      description: s.description ?? "",
      host: s.host,
      username: "",
      password: "",
      vendor: s.vendor ?? "dell",
    });
    setEditingId(s.id);
    setShowForm(false);
  };

  const saveEdit = async (id: string) => {
    if (!editForm.host.trim()) {
      toast.error("Host is required");
      return;
    }
    // server_id is NEVER sent (D-13). Omit blank username/password so the
    // backend keeps the existing encrypted credentials (do NOT send "").
    const payload: Record<string, unknown> = {
      name: editForm.name,
      description: editForm.description,
      host: editForm.host,
      vendor: editForm.vendor,
    };
    if (editForm.username.trim()) payload.username = editForm.username;
    if (editForm.password.trim()) payload.password = editForm.password;
    try {
      await put(`/api/servers/${id}`, payload);
      toast.success("Server updated");
      setEditingId(null);
      await loadServers();
    } catch {
      toast.error("Failed to update server");
    }
  };

  // ENABLE: /configure bootstrap case (auth is OFF, no prior session needed per REVIEWS #1).
  // Always requires fresh creds (D-09); operator stays logged in via the cookie /configure issues.
  // A session-expiry 401 here is handled by the global interceptor (REVIEWS #6).
  const enableAuth = async () => {
    if (!secUsername.trim() || !secPassword.trim()) {
      toast.error("Username and password are required");
      return;
    }
    setSecBusy(true);
    try {
      await post("/api/auth/configure", { username: secUsername, password: secPassword });
      useAuthStore.setState({ authEnabled: true, authenticated: true, hasUser: true, username: secUsername });
      setSecUsername("");
      setSecPassword("");
      toast.success("Authentication enabled");
    } catch {
      toast.error("Failed to enable authentication");
    } finally {
      setSecBusy(false);
    }
  };

  // DISABLE: /toggle {enabled:false} only — the stored user row is KEPT (D-10, no credential wipe,
  // no re-auth). The operator has a valid session, accepted by the backend's first-run-aware helper.
  const disableAuth = async () => {
    setSecBusy(true);
    try {
      await post("/api/auth/toggle", { enabled: false });
      useAuthStore.setState({ authEnabled: false }); // user row KEPT (D-10); hasUser stays true
      toast.success("Authentication disabled");
    } catch {
      toast.error("Failed to disable authentication");
    } finally {
      setSecBusy(false);
    }
  };

  const openAddForm = () => {
    // Add-form / edit-form mutual exclusivity.
    setShowForm((prev) => {
      const next = !prev;
      if (next) setEditingId(null);
      return next;
    });
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
              <button onClick={openAddForm} className="flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-xs font-medium hover:bg-muted">
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
              <EmptyState
                icon={ServerIcon}
                title="No servers configured"
                description="Add one to start monitoring."
                action={{ label: "Add a Server", onClick: () => { setEditingId(null); setShowForm(true); } }}
                className="py-12"
              />
            ) : (
              <div className="space-y-2">
                {servers.map((s) => (
                  <div key={s.id}>
                    <div className="flex items-center gap-3 rounded-md border border-border p-3">
                      <div className={`h-2.5 w-2.5 shrink-0 rounded-full ${s.is_online ? "bg-emerald-500" : "bg-red-500"}`} />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium">{s.name}</div>
                        <div className="font-mono text-xs text-muted-foreground">{s.host}</div>
                      </div>
                      <div className="flex gap-1">
                        <button onClick={() => startEdit(s)} aria-label="Edit server" className="rounded-md border border-border p-1.5 hover:bg-muted">
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button onClick={() => testServer(s.id)} disabled={testing === s.id} aria-label="Test connection" className="rounded-md border border-border p-1.5 hover:bg-muted">
                          <TestTube className={cn("h-3.5 w-3.5", testing === s.id && "animate-spin")} />
                        </button>
                        <button onClick={() => deleteServer(s.id)} aria-label="Delete server" className="rounded-md border border-border p-1.5 hover:bg-muted text-red-500">
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>

                    {editingId === s.id && (
                      <div className="mt-2 space-y-3 rounded-md border border-border bg-muted/50 p-4">
                        <div className="grid grid-cols-2 gap-3">
                          <input placeholder="Name (e.g., Dell R720)" value={editForm.name} onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm" />
                          <input placeholder="Description (optional)" value={editForm.description} onChange={(e) => setEditForm({ ...editForm, description: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm" />
                          <input placeholder="BMC IP (e.g., 192.0.2.10)" value={editForm.host} onChange={(e) => setEditForm({ ...editForm, host: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm" />
                          <select value={editForm.vendor} onChange={(e) => setEditForm({ ...editForm, vendor: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm">
                            <option value="dell">Dell</option>
                            <option value="supermicro">Supermicro</option>
                            <option value="hpe">HPE</option>
                            <option value="generic">Generic</option>
                          </select>
                          <input placeholder="Username (leave blank to keep current)" value={editForm.username} onChange={(e) => setEditForm({ ...editForm, username: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm" />
                          <input type="password" placeholder="Password (leave blank to keep current)" value={editForm.password} onChange={(e) => setEditForm({ ...editForm, password: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm font-mono" />
                        </div>
                        <div className="flex justify-end gap-2">
                          <button onClick={() => setEditingId(null)} className="rounded-md px-3 py-1.5 text-xs hover:bg-muted">Discard Changes</button>
                          <button onClick={() => saveEdit(s.id)} className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground">Save Changes</button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Security */}
          <div className="rounded-lg border border-border bg-card p-5">
            <div className="mb-4 flex items-center gap-2">
              {authEnabled ? (
                <ShieldCheck className="h-4 w-4 text-emerald-500" />
              ) : (
                <ShieldOff className="h-4 w-4 text-muted-foreground" />
              )}
              <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Security</h2>
            </div>

            {authEnabled ? (
              <div className="space-y-3">
                <p className="text-sm text-muted-foreground">Authentication is enabled.</p>
                <button
                  onClick={disableAuth}
                  disabled={secBusy}
                  className="rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:opacity-50"
                >
                  Disable Authentication
                </button>
                <p className="text-xs text-muted-foreground">
                  Enabling again will require setting a new username and password.
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-sm text-muted-foreground">
                  Authentication is disabled — the dashboard is open on your network.
                </p>
                <div className="grid grid-cols-2 gap-3">
                  <input
                    placeholder="Username"
                    value={secUsername}
                    onChange={(e) => setSecUsername(e.target.value)}
                    className="rounded-md border border-border bg-background px-3 py-1.5 text-sm"
                  />
                  <input
                    type="password"
                    placeholder="Password"
                    value={secPassword}
                    onChange={(e) => setSecPassword(e.target.value)}
                    className="rounded-md border border-border bg-background px-3 py-1.5 text-sm font-mono"
                  />
                </div>
                <button
                  onClick={enableAuth}
                  disabled={secBusy}
                  className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50"
                >
                  Enable Authentication
                </button>
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
                  <div className="mt-1.5 flex items-center gap-2">
                    <a href="https://github.com/dev-luigi" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground">
                      <Code2 className="h-3 w-3" /> dev-luigi <ExternalLink className="h-2.5 w-2.5" />
                    </a>
                    <a href="https://github.com/sponsors/dev-luigi" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded-md border border-pink-500/30 bg-pink-500/10 px-2 py-0.5 text-[11px] font-medium text-pink-400 transition-colors hover:bg-pink-500/20">
                      <Heart className="h-3 w-3 fill-current" /> Sponsor <ExternalLink className="h-2.5 w-2.5" />
                    </a>
                  </div>
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
