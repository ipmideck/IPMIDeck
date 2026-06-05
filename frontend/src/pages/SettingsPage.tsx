import { useEffect, useState } from "react";
import { useTranslation, Trans } from "react-i18next";
import { Header } from "@/components/layout/Header";
import { useServerStore, type Server } from "@/stores/server-store";
import { useThemeStore } from "@/stores/theme-store";
import { useAuthStore } from "@/stores/auth-store";
import { useBackendOnline } from "@/stores/connection-store";
import { get, post, put, del } from "@/api/client";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Plus, Trash2, TestTube, Pencil, ExternalLink, Heart, Code2, Moon, Sun, Monitor, Server as ServerIcon, ShieldCheck, ShieldOff } from "lucide-react";
import { EmptyState } from "@/components/common/EmptyState";
import { LanguageSelect } from "@/components/LanguageSelect";

export default function SettingsPage() {
  const { t } = useTranslation();
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
  // Confirm-password: re-typing the password protects against typos when enabling
  // auth — otherwise the operator could lock themselves out with an unrecoverable
  // misspelling. Mirrors the same guard on the setup wizard's auth step.
  const [secPasswordConfirm, setSecPasswordConfirm] = useState("");
  const [secBusy, setSecBusy] = useState(false);
  // Disable-auth confirmation flow: clicking "Disable" expands an inline form that
  // asks for the CURRENT password (intent confirmation, not a credential change).
  // Backend rejects the call without it when has_user is true.
  const [secDisableConfirm, setSecDisableConfirm] = useState(false);
  const [secCurrentPassword, setSecCurrentPassword] = useState("");

  // Backend connectivity — every mutation button on this page must disable when the
  // WS is down so the user doesn't fire requests that will hang (and so an auth-toggle
  // while offline can't leave the user locked out of an unreachable backend).
  const online = useBackendOnline();
  const offlineTip = online ? undefined : t("header.backendDisconnected");

  const loadServers = async () => {
    try {
      const data = await get<{ servers: Server[] }>("/api/servers");
      setServers(data.servers);
    } catch { /* ignore */ }
  };

  useEffect(() => { loadServers(); }, []);

  const addServer = async () => {
    if (!form.host || !form.username || !form.password) {
      toast.error(t("settings.credentialsRequired"));
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
        toast.success(t("settings.serverAdded"));
        setForm({ name: "", description: "", host: "", username: "", password: "", vendor: "dell" });
        setShowForm(false);
        await loadServers();
      }
    } catch {
      toast.error(t("settings.serverAddFailed"));
    }
  };

  const deleteServer = async (id: string) => {
    try {
      await del(`/api/servers/${id}`);
      toast.success(t("settings.serverRemoved"));
      await loadServers();
    } catch {
      toast.error(t("settings.serverDeleteFailed"));
    }
  };

  const testServer = async (id: string) => {
    setTesting(id);
    try {
      const res = await post<{ success: boolean; power_status?: string; error?: string }>(`/api/servers/${id}/test`);
      if (res.success) {
        toast.success(t("settings.testOk", { status: res.power_status }));
        await loadServers();
      } else {
        toast.error(res.error || t("settings.connectionFailed"));
      }
    } catch {
      toast.error(t("settings.connectionFailed"));
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
      toast.error(t("settings.hostRequired"));
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
      toast.success(t("settings.serverUpdated"));
      setEditingId(null);
      await loadServers();
    } catch {
      toast.error(t("settings.serverUpdateFailed"));
    }
  };

  // ENABLE: /configure bootstrap case (auth is OFF, no prior session needed per REVIEWS #1).
  // Always requires fresh creds (D-09); operator stays logged in via the cookie /configure issues.
  // A session-expiry 401 here is handled by the global interceptor (REVIEWS #6).
  const enableAuth = async () => {
    if (!secUsername.trim() || !secPassword.trim()) {
      toast.error(t("settings.usernamePasswordRequired"));
      return;
    }
    if (secPassword !== secPasswordConfirm) {
      toast.error(t("settings.passwordsDoNotMatch"));
      return;
    }
    setSecBusy(true);
    try {
      await post("/api/auth/configure", { username: secUsername, password: secPassword });
      useAuthStore.setState({ authEnabled: true, authenticated: true, hasUser: true, username: secUsername });
      setSecUsername("");
      setSecPassword("");
      setSecPasswordConfirm("");
      toast.success(t("settings.authEnabledToast"));
    } catch {
      toast.error(t("settings.authEnableFailed"));
    } finally {
      setSecBusy(false);
    }
  };

  // DISABLE: /toggle {enabled:false}. Requires the operator to re-enter their
  // CURRENT password — defends against accidental clicks and stale-session takeover.
  // Stored user row is KEPT (D-10, no credential wipe). The session cookie remains
  // valid until logout / expiry; the backend just stops enforcing auth.
  const disableAuth = async () => {
    if (!secCurrentPassword.trim()) {
      toast.error(t("settings.currentPasswordRequired"));
      return;
    }
    setSecBusy(true);
    try {
      const res = await post<{ success: boolean; error?: string }>(
        "/api/auth/toggle",
        { enabled: false, current_password: secCurrentPassword }
      );
      if (!res.success) {
        toast.error(res.error || t("settings.authDisableFailed"));
        return;
      }
      useAuthStore.setState({ authEnabled: false }); // user row KEPT (D-10); hasUser stays true
      setSecDisableConfirm(false);
      setSecCurrentPassword("");
      toast.success(t("settings.authDisabledToast"));
    } catch {
      toast.error(t("settings.authDisableFailed"));
    } finally {
      setSecBusy(false);
    }
  };

  const cancelDisable = () => {
    setSecDisableConfirm(false);
    setSecCurrentPassword("");
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
      <Header title={t("nav.settings")} />
      <div className="flex-1 overflow-auto p-6">
        <div className="mx-auto max-w-2xl space-y-6">

          {/* Servers */}
          <div className="rounded-lg border border-border bg-card p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">{t("settings.servers")}</h2>
              <button
                onClick={openAddForm}
                disabled={!online}
                title={offlineTip}
                className="flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-xs font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Plus className="h-3 w-3" /> {t("settings.add")}
              </button>
            </div>

            {showForm && (
              <div className="mb-4 space-y-3 rounded-md border border-border bg-muted/50 p-4">
                <div className="grid grid-cols-2 gap-3">
                  <input placeholder={t("settings.namePlaceholder")} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm" />
                  <input placeholder={t("settings.descriptionPlaceholder")} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm" />
                  <input placeholder={t("settings.hostPlaceholder")} value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm" />
                  <select value={form.vendor} onChange={(e) => setForm({ ...form, vendor: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm">
                    <option value="dell">{t("settings.vendorDell")}</option>
                    <option value="supermicro">{t("settings.vendorSupermicro")}</option>
                    <option value="hpe">{t("settings.vendorHpe")}</option>
                    <option value="generic">{t("settings.vendorGeneric")}</option>
                  </select>
                  <input placeholder={t("settings.usernamePlaceholder")} value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm" />
                  <input type="password" placeholder={t("settings.passwordPlaceholder")} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm font-mono" />
                </div>
                <div className="flex justify-end gap-2">
                  <button onClick={() => setShowForm(false)} className="rounded-md px-3 py-1.5 text-xs hover:bg-muted">{t("settings.cancel")}</button>
                  <button
                    onClick={addServer}
                    disabled={!online}
                    title={offlineTip}
                    className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {t("settings.addServer")}
                  </button>
                </div>
              </div>
            )}

            {servers.length === 0 ? (
              <EmptyState
                icon={ServerIcon}
                title={t("settings.noServersTitle")}
                description={t("settings.noServersDescription")}
                action={{ label: t("settings.addAServer"), onClick: () => { setEditingId(null); setShowForm(true); } }}
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
                        <button onClick={() => startEdit(s)} aria-label={t("settings.aria.editServer")} className="rounded-md border border-border p-1.5 hover:bg-muted">
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={() => testServer(s.id)}
                          disabled={testing === s.id || !online}
                          title={offlineTip}
                          aria-label={t("settings.aria.testConnection")}
                          className="rounded-md border border-border p-1.5 hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          <TestTube className={cn("h-3.5 w-3.5", testing === s.id && "animate-spin")} />
                        </button>
                        <button
                          onClick={() => deleteServer(s.id)}
                          disabled={!online}
                          title={offlineTip}
                          aria-label={t("settings.aria.deleteServer")}
                          className="rounded-md border border-border p-1.5 hover:bg-muted text-red-500 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>

                    {editingId === s.id && (
                      <div className="mt-2 space-y-3 rounded-md border border-border bg-muted/50 p-4">
                        <div className="grid grid-cols-2 gap-3">
                          <input placeholder={t("settings.namePlaceholder")} value={editForm.name} onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm" />
                          <input placeholder={t("settings.descriptionPlaceholder")} value={editForm.description} onChange={(e) => setEditForm({ ...editForm, description: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm" />
                          <input placeholder={t("settings.hostPlaceholder")} value={editForm.host} onChange={(e) => setEditForm({ ...editForm, host: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm" />
                          <select value={editForm.vendor} onChange={(e) => setEditForm({ ...editForm, vendor: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm">
                            <option value="dell">{t("settings.vendorDell")}</option>
                            <option value="supermicro">{t("settings.vendorSupermicro")}</option>
                            <option value="hpe">{t("settings.vendorHpe")}</option>
                            <option value="generic">{t("settings.vendorGeneric")}</option>
                          </select>
                          <input placeholder={t("settings.editUsernamePlaceholder")} value={editForm.username} onChange={(e) => setEditForm({ ...editForm, username: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm" />
                          <input type="password" placeholder={t("settings.editPasswordPlaceholder")} value={editForm.password} onChange={(e) => setEditForm({ ...editForm, password: e.target.value })} className="rounded-md border border-border bg-background px-3 py-1.5 text-sm font-mono" />
                        </div>
                        <div className="flex justify-end gap-2">
                          <button onClick={() => setEditingId(null)} className="rounded-md px-3 py-1.5 text-xs hover:bg-muted">{t("settings.discardChanges")}</button>
                          <button
                            onClick={() => saveEdit(s.id)}
                            disabled={!online}
                            title={offlineTip}
                            className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {t("settings.saveChanges")}
                          </button>
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
              <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">{t("settings.security")}</h2>
            </div>

            {authEnabled ? (
              <div className="space-y-3">
                <p className="text-sm text-muted-foreground">{t("settings.authEnabledLabel")}</p>
                {!secDisableConfirm ? (
                  <button
                    onClick={() => setSecDisableConfirm(true)}
                    disabled={secBusy || !online}
                    title={offlineTip}
                    className="rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {t("settings.disableAuth")}
                  </button>
                ) : (
                  <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 space-y-3">
                    <p className="text-xs text-muted-foreground">
                      {t("settings.disableConfirmText")}
                    </p>
                    <input
                      type="password"
                      placeholder={t("settings.currentPasswordPlaceholder")}
                      value={secCurrentPassword}
                      onChange={(e) => setSecCurrentPassword(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") disableAuth(); }}
                      autoFocus
                      className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm font-mono"
                    />
                    <div className="flex gap-2">
                      <button
                        onClick={cancelDisable}
                        disabled={secBusy}
                        className="flex-1 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-muted disabled:opacity-50"
                      >
                        {t("settings.cancel")}
                      </button>
                      <button
                        onClick={disableAuth}
                        disabled={secBusy || !online || !secCurrentPassword.trim()}
                        title={offlineTip}
                        className="flex-1 rounded-md bg-red-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-600 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {secBusy ? t("settings.disabling") : t("settings.confirmDisable")}
                      </button>
                    </div>
                  </div>
                )}
                <p className="text-xs text-muted-foreground">
                  {t("settings.reEnableNote")}
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-sm text-muted-foreground">
                  {t("settings.authDisabledLabel")}
                </p>
                <div className="grid grid-cols-2 gap-3">
                  <input
                    placeholder={t("settings.secUsernamePlaceholder")}
                    value={secUsername}
                    onChange={(e) => setSecUsername(e.target.value)}
                    className="rounded-md border border-border bg-background px-3 py-1.5 text-sm"
                  />
                  <input
                    type="password"
                    placeholder={t("settings.secPasswordPlaceholder")}
                    value={secPassword}
                    onChange={(e) => setSecPassword(e.target.value)}
                    className="rounded-md border border-border bg-background px-3 py-1.5 text-sm font-mono"
                  />
                </div>
                <input
                  type="password"
                  placeholder={t("settings.confirmPasswordPlaceholder")}
                  value={secPasswordConfirm}
                  onChange={(e) => setSecPasswordConfirm(e.target.value)}
                  className={cn(
                    "w-full rounded-md border bg-background px-3 py-1.5 text-sm font-mono",
                    secPassword && secPasswordConfirm && secPassword !== secPasswordConfirm
                      ? "border-red-500/60"
                      : "border-border"
                  )}
                />
                {secPassword && secPasswordConfirm && secPassword !== secPasswordConfirm && (
                  <p className="text-xs text-red-500">{t("settings.passwordsDoNotMatch")}</p>
                )}
                <button
                  onClick={enableAuth}
                  disabled={secBusy || !online}
                  title={offlineTip}
                  className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {t("settings.enableAuth")}
                </button>
              </div>
            )}
          </div>

          {/* Appearance */}
          <div className="rounded-lg border border-border bg-card p-5">
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-muted-foreground">{t("settings.appearance")}</h2>
            <div className="flex gap-2">
              {[
                { value: "dark" as const, label: t("settings.themeDark"), icon: Moon },
                { value: "light" as const, label: t("settings.themeLight"), icon: Sun },
                { value: "system" as const, label: t("settings.themeSystem"), icon: Monitor },
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
            {/* Language switcher (D-11/D-12): native names, switchable anytime, applies immediately + persists via the i18next detector. */}
            <div className="mt-4 flex items-center justify-between gap-3">
              <span className="text-sm font-medium">{t("settings.language")}</span>
              <LanguageSelect className="rounded-md border border-border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50" />
            </div>
          </div>

          {/* About */}
          <div className="rounded-lg border border-border bg-card p-5">
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-muted-foreground">{t("settings.about")}</h2>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">{t("settings.version")}</span>
                <span className="font-mono text-sm">2.0.0-alpha.1</span>
              </div>
              <div className="border-t border-border" />
              <div className="flex items-start gap-3 pt-1">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-muted text-sm font-semibold">LT</div>
                <div>
                  <p className="text-sm font-medium">Luigi Tanzillo</p>
                  <p className="text-xs text-muted-foreground">{t("settings.creatorRole")}</p>
                  <div className="mt-1.5 flex items-center gap-2">
                    <a href="https://github.com/dev-luigi" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground">
                      <Code2 className="h-3 w-3" /> dev-luigi <ExternalLink className="h-2.5 w-2.5" />
                    </a>
                    <a href="https://github.com/sponsors/dev-luigi" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded-md border border-pink-500/30 bg-pink-500/10 px-2 py-0.5 text-[11px] font-medium text-pink-400 transition-colors hover:bg-pink-500/20">
                      <Heart className="h-3 w-3 fill-current" /> {t("settings.sponsor")} <ExternalLink className="h-2.5 w-2.5" />
                    </a>
                  </div>
                </div>
              </div>
              <div className="border-t border-border" />
              <p className="flex items-center gap-1 text-xs text-muted-foreground">
                <Trans i18nKey="settings.about.madeWith">
                  Made with <Heart className="h-3 w-3 text-red-500" /> for the homelab community
                </Trans>
              </p>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
