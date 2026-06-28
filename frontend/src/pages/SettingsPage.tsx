import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { Header } from "@/components/layout/Header";
import { useServerStore, type Server } from "@/stores/server-store";
import { useCurrencyStore } from "@/stores/currency-store";
import { useEnergyResetStore } from "@/stores/energy-reset-store";
import { SUPPORTED_CURRENCIES, currencyOptionLabel, type CurrencyCode } from "@/lib/currency";
import { useThemeStore } from "@/stores/theme-store";
import { useTourStore } from "@/stores/tour-store";
import { useAuthStore } from "@/stores/auth-store";
import { useAlertingStore } from "@/stores/alerting-store";
import { useBackendOnline } from "@/stores/connection-store";
import { get, post, put, del } from "@/api/client";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Plus, Trash2, TestTube, Pencil, ExternalLink, Heart, Code2, Globe, Moon, Sun, Monitor, Server as ServerIcon, ShieldCheck, ShieldOff, Fan, Zap, Bell, Lock, Database, Archive } from "lucide-react";
import { EmptyState } from "@/components/common/EmptyState";
import { LanguageSelect } from "@/components/LanguageSelect";

/** Human-readable byte size for the Data card DB-size readout (04-W5-01). */
function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(1)} GB`;
}

export default function SettingsPage() {
  const { t, i18n } = useTranslation();
  const { servers, setServers } = useServerStore();
  const { theme, setTheme } = useThemeStore();
  const startTour = useTourStore((s) => s.start);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", host: "", username: "", password: "", vendor: "dell" });
  const [testing, setTesting] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState({ name: "", description: "", host: "", username: "", password: "", vendor: "dell", cost_per_kwh: null as number | null });
  // 04-W2-02: ref on the cost input — reused by 04-03's "Configura tariffa" CTA
  // (hash navigation /settings#server-{id}-cost scrolls + focuses this field).
  const costInputRef = useRef<HTMLInputElement>(null);

  // 04-W2-04: respond to the "Configure tariff" CTA hash (#server-{id}-cost).
  // Server IDs are STRINGS (UUIDs) — the regex captures any non-`#` suffix without
  // int coercion (Decision C). Expand the matching server's edit form, scroll the
  // cost input into view, focus it, then clear the hash so it doesn't persist.
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    const match = location.hash.match(/^#server-(.+)-cost$/);
    if (!match) return;
    const targetId = match[1]; // string — Decision C, no Number()/parseInt
    if (!targetId || targetId === "undefined" || targetId === "new") return;
    // GAP-B (04-13): look up the target server and PREFILL editForm — not just
    // setEditingId. The form fields are controlled by editForm, so rendering the
    // form without populating it left name/host/vendor blank and saveEdit bailed on
    // the empty-host guard (no PUT). Read servers from the store at call time to keep
    // the deps array minimal (the deep-link arrives from the dashboard where servers
    // are already loaded). If no server matches the id, do NOT open a blank form.
    const target = useServerStore.getState().servers.find((s) => s.id === targetId);
    if (target == null) return;
    // startEdit prefills editForm from the server AND setEditingId(target.id) AND
    // setShowForm(false). Guard against clobbering an edit already in progress for
    // this same server (belt-and-suspenders — the hash is cleared in the rAF below).
    if (editingId !== targetId) startEdit(target);
    // Wait for the form to render, then scroll + focus the cost input.
    const tick = requestAnimationFrame(() => {
      const el = document.getElementById(`server-${targetId}-cost`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        (el as HTMLInputElement).focus();
      }
      // Clear the hash so it doesn't persist in history.
      navigate(location.pathname + location.search, { replace: true });
    });
    return () => cancelAnimationFrame(tick);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- editingId/startEdit are
    // read for a one-shot deep-link prefill; re-running on their identity change would
    // re-fire the scroll/focus + hash-clear on every keystroke in the edit form.
  }, [location.hash, location.pathname, location.search, navigate]);

  // 04-W2-03: global currency selector (Appearance card, below Language).
  const currency = useCurrencyStore((s) => s.currency);
  const setCurrency = useCurrencyStore((s) => s.setCurrency);
  const hydrateCurrency = useCurrencyStore((s) => s.hydrate);
  useEffect(() => { hydrateCurrency(); }, [hydrateCurrency]);

  // 04.3 D-09: zero-drift version — fetch the RUNNING backend's version from /api/health
  // (the SPA is served by the same FastAPI process, so this always matches what is deployed).
  // No baked literal. Leave null on failure → the `—` placeholder renders.
  const [appVersion, setAppVersion] = useState<string | null>(null);
  useEffect(() => {
    get<{ version: string }>("/api/health")
      .then((h) => setAppVersion(h.version))
      .catch(() => { /* leave null → render the — placeholder */ });
  }, []);

  // 04-W2-07: Energy Counters card. Per-server + reset-all, each behind the
  // inline-expand-confirm pattern. Server IDs are STRINGS (Decision C). resetAll
  // merges the backend's affected_ids (Decision P, in the store).
  const [resetConfirmId, setResetConfirmId] = useState<string | null>(null);
  const [resetAllConfirm, setResetAllConfirm] = useState(false);
  const resets = useEnergyResetStore((s) => s.resets);
  const resetServer = useEnergyResetStore((s) => s.resetServer);
  const resetAll = useEnergyResetStore((s) => s.resetAll);
  const hydrateResets = useEnergyResetStore((s) => s.hydrate);
  useEffect(() => { hydrateResets(); }, [hydrateResets]);
  const energyLocale = i18n.resolvedLanguage || "en";

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

  // 04-W1-01 (Plan 04-01, Task 2): FanPilot card — auto-recover on BMC offline.
  // Persisted in app_config via /api/system/app-config/fanpilot.auto_recover_on_offline
  // (Decision A1: backend uses current globals; Decision B: /system/* prefix).
  // Default ON (safety-first) — applies if the row is missing.
  const [autoRecover, setAutoRecover] = useState(true);
  const [fanpilotSaving, setFanpilotSaving] = useState(false);

  useEffect(() => {
    // GET via NAMED imports get/put (Decision D — no `apiClient` exists).
    get<{ success: boolean; key: string; value: boolean | null }>(
      "/api/system/app-config/fanpilot.auto_recover_on_offline"
    )
      .then((r) => {
        if (r.value !== null && r.value !== undefined) {
          setAutoRecover(Boolean(r.value));
        }
        // value === null means the row hasn't been written yet — keep default ON.
      })
      .catch(() => { /* default ON; backend may be down (offline indicator handles it) */ });
  }, []);

  const toggleAutoRecover = async () => {
    const next = !autoRecover;
    // Optimistic flip rolled back on failure to avoid a stuck toggle.
    setAutoRecover(next);
    setFanpilotSaving(true);
    try {
      await put("/api/system/app-config/fanpilot.auto_recover_on_offline", { value: next });
    } catch {
      setAutoRecover(!next);
      toast.error(t("settings.fanpilot.saveFailed"));
    } finally {
      setFanpilotSaving(false);
    }
  };

  // quick-260626-4px: FanPilot resume threshold. Persisted in SECONDS in app_config
  // (fanpilot.resume_threshold_seconds, default 3600 = 1h) but DISPLAYED in hours.
  // Store + expose only — consumed later by Phase 5 startup-resume logic (inert now).
  const [resumeHours, setResumeHours] = useState(1);
  const [resumeSavedHours, setResumeSavedHours] = useState(1);

  useEffect(() => {
    get<{ success: boolean; key: string; value: number | string | null }>(
      "/api/system/app-config/fanpilot.resume_threshold_seconds"
    )
      .then((r) => {
        if (r.value !== null && r.value !== undefined && r.value !== "") {
          const secs = Number(r.value);
          if (!Number.isNaN(secs)) {
            const hrs = secs / 3600;
            setResumeHours(hrs);
            setResumeSavedHours(hrs);
          }
        }
        // null/empty means the row hasn't been written — keep default 1h.
      })
      .catch(() => { /* default 1h; offline indicator handles connectivity */ });
  }, []);

  const onSaveResumeThreshold = async () => {
    try {
      await put("/api/system/app-config/fanpilot.resume_threshold_seconds", {
        value: Math.round(resumeHours * 3600),
      });
      setResumeSavedHours(resumeHours);
      toast.success(t("settings.fanpilot.resumeThresholdSaved"));
    } catch {
      toast.error(t("settings.fanpilot.saveFailed"));
    }
  };

  // quick-260626-4px: FanPilot fail-safe behavior. failsafe_mode = "bmc_auto" | "fixed"
  // (default "fixed" — safety-first "fail to full speed"); failsafe_speed 0-100 (default
  // 100). Wired LIVE into offline/stale recovery on the backend. Mode persists optimistically
  // on change; the fixed-speed slider persists via its own Save button.
  const [failsafeMode, setFailsafeMode] = useState<"bmc_auto" | "fixed">("fixed");
  const [failsafeSpeed, setFailsafeSpeed] = useState(100);
  const [failsafeSpeedSaved, setFailsafeSpeedSaved] = useState(100);

  useEffect(() => {
    get<{ success: boolean; key: string; value: number | string | null }>(
      "/api/system/app-config/fanpilot.failsafe_mode"
    )
      .then((r) => {
        if (r.value === "bmc_auto" || r.value === "fixed") setFailsafeMode(r.value);
        // null/anything-else -> keep default "fixed".
      })
      .catch(() => { /* default fixed */ });
    get<{ success: boolean; key: string; value: number | string | null }>(
      "/api/system/app-config/fanpilot.failsafe_speed"
    )
      .then((r) => {
        if (r.value !== null && r.value !== undefined && r.value !== "") {
          const n = Number(r.value);
          if (!Number.isNaN(n)) {
            const clamped = Math.min(100, Math.max(0, Math.round(n)));
            setFailsafeSpeed(clamped);
            setFailsafeSpeedSaved(clamped);
          }
        }
        // null/empty -> keep default 100.
      })
      .catch(() => { /* default 100 */ });
  }, []);

  const onSelectFailsafeMode = async (mode: "bmc_auto" | "fixed") => {
    if (mode === failsafeMode) return;
    const prev = failsafeMode;
    setFailsafeMode(mode); // optimistic
    setFanpilotSaving(true);
    try {
      await put("/api/system/app-config/fanpilot.failsafe_mode", { value: mode });
    } catch {
      setFailsafeMode(prev);
      toast.error(t("settings.fanpilot.saveFailed"));
    } finally {
      setFanpilotSaving(false);
    }
  };

  const onSaveFailsafeSpeed = async () => {
    try {
      await put("/api/system/app-config/fanpilot.failsafe_speed", { value: failsafeSpeed });
      setFailsafeSpeedSaved(failsafeSpeed);
      toast.success(t("settings.fanpilot.failsafeSpeedSaved"));
    } catch {
      toast.error(t("settings.fanpilot.saveFailed"));
    }
  };

  // 04-W5-01: Data card — retention slider + DB stats + immediate cleanup. Persists
  // the retention window to app_config via PUT /api/system/retention-days (Decision B,
  // /system/* prefix; Decision A1 current globals on the backend); the cleanup loop reads
  // it back. Named client imports get/post/put (Decision D). "Run cleanup now" deletes
  // sensor_readings older than the window NOW — gated behind an inline confirm.
  const [retentionDays, setRetentionDays] = useState(30);
  const [retentionSaved, setRetentionSaved] = useState(30);
  const [dbStats, setDbStats] = useState({
    db_size_bytes: 0,
    sensor_readings_rows: 0,
    oldest_reading_timestamp: null as string | null,
  });
  const [cleanupConfirm, setCleanupConfirm] = useState(false);
  const [cleanupBusy, setCleanupBusy] = useState(false);
  const dataLocale = i18n.resolvedLanguage || "en";

  const refreshDbStats = async () => {
    try {
      const r = await get<{
        success: boolean;
        db_size_bytes: number;
        sensor_readings_rows: number;
        oldest_reading_timestamp: string | null;
      }>("/api/system/db-stats");
      if (r.success) {
        setDbStats({
          db_size_bytes: r.db_size_bytes,
          sensor_readings_rows: r.sensor_readings_rows,
          oldest_reading_timestamp: r.oldest_reading_timestamp,
        });
      }
    } catch { /* offline indicator handles connectivity */ }
  };

  useEffect(() => {
    get<{ success: boolean; days: number }>("/api/system/retention-days")
      .then((r) => {
        if (r.success) {
          setRetentionDays(r.days);
          setRetentionSaved(r.days);
        }
      })
      .catch(() => { /* keep default 30 */ });
    void refreshDbStats();
  }, []);

  const onSaveRetention = async () => {
    try {
      await put("/api/system/retention-days", { days: retentionDays });
      setRetentionSaved(retentionDays);
      toast.success(t("settings.data.retentionSaved"));
    } catch (e: any) {
      toast.error(String(e?.message ?? e));
    }
  };

  const onRunCleanup = async () => {
    setCleanupBusy(true);
    try {
      const r = await post<{ success: boolean; deleted_rows: number }>(
        "/api/system/retention-cleanup-now"
      );
      if (r.success) {
        toast.success(t("settings.data.cleanupDone"));
        setCleanupConfirm(false);
        await refreshDbStats();
      }
    } catch (e: any) {
      toast.error(String(e?.message ?? e));
      setCleanupConfirm(false);
    } finally {
      setCleanupBusy(false);
    }
  };

  // 04-W3-01: Alerting card — browser-notifications opt-in. The store owns the
  // permission request flow (Notification.requestPermission() runs inside enable(),
  // which is invoked from the toggle onClick) + persists alerting.notifications_enabled
  // in app_config (Decision B: /api/system/...). Severity filter (critical/warning only)
  // is enforced in useWebSocket.ts.
  const notificationsEnabled = useAlertingStore((s) => s.notificationsEnabled);
  const permission = useAlertingStore((s) => s.permission);
  const enableAlerting = useAlertingStore((s) => s.enable);
  const disableAlerting = useAlertingStore((s) => s.disable);
  const hydrateAlerting = useAlertingStore((s) => s.hydrate);
  useEffect(() => { hydrateAlerting(); }, [hydrateAlerting]);

  // 04-W4-03: Network card — HTTPS toggle + self-signed cert generation. Backend
  // persists to config.yaml (PUT /api/system/https, POST /api/system/gen-cert) via the
  // /system/* prefix (Decision B) using current globals (Decision A1). Named client
  // imports get/post/put (Decision D). HTTPS only takes effect after a restart, so the
  // toggle is informational + gated behind a confirm; the yellow banner explains it.
  const [https, setHttps] = useState(false);
  const [certPath, setCertPath] = useState("");
  const [keyPath, setKeyPath] = useState("");
  const [httpsConfirm, setHttpsConfirm] = useState(false);
  const [networkBusy, setNetworkBusy] = useState(false);

  const onGenCert = async () => {
    setNetworkBusy(true);
    try {
      const r = await post<{ success: boolean; cert_path?: string; key_path?: string; error?: string }>(
        "/api/system/gen-cert"
      );
      if (r.success && r.cert_path && r.key_path) {
        setCertPath(r.cert_path);
        setKeyPath(r.key_path);
        toast.success(t("settings.network.genCertDone"));
      } else {
        toast.error(r.error || t("settings.network.genCertDone"));
      }
    } catch {
      toast.error(t("settings.network.genCertDone"));
    } finally {
      setNetworkBusy(false);
    }
  };

  const applyHttps = async (next: boolean) => {
    setNetworkBusy(true);
    try {
      await put("/api/system/https", { https: next });
      setHttps(next);
      setHttpsConfirm(false);
    } catch {
      toast.error(t("settings.network.genCertDone"));
    } finally {
      setNetworkBusy(false);
    }
  };

  const onToggleHttps = async () => {
    // Enabling HTTPS expands the confirm banner first (restart + self-signed warning).
    if (!https && !httpsConfirm) {
      setHttpsConfirm(true);
      return;
    }
    await applyHttps(!https);
  };

  // 04-W6-03: Backup & Restore card. Backup POSTs to /api/system/backup and streams a
  // zip (ipmideck.db + config.yaml + encryption.key) — use the native fetch + blob path,
  // NOT the @/api/client wrapper, because the body is a binary stream. Restore uploads the
  // zip as a RAW application/zip body to /api/system/restore (staged + applied on next
  // restart) — no python-multipart dep. The restore CTA is gated behind an inline red
  // confirm, same pattern as disableAuth.
  const [restoreFile, setRestoreFile] = useState<File | null>(null);
  const [restoreConfirm, setRestoreConfirm] = useState(false);
  const restoreInputRef = useRef<HTMLInputElement>(null);

  const onDownloadBackup = async () => {
    try {
      const res = await fetch("/api/system/backup", { method: "POST", credentials: "include" });
      if (!res.ok) throw new Error("backup_failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `ipmideck-backup-${new Date().toISOString().replace(/[:.]/g, "-")}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success(t("settings.backup.downloadDone"));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  };

  const onRestore = async () => {
    if (!restoreFile) return;
    try {
      // Send the zip as the RAW body (application/zip) — the backend reads
      // request.body() so we avoid the python-multipart dependency.
      const res = await fetch("/api/system/restore", {
        method: "POST",
        headers: { "Content-Type": "application/zip" },
        body: restoreFile,
        credentials: "include",
      });
      const j = (await res.json()) as { success: boolean; error?: string };
      if (j.success) {
        toast.success(t("settings.backup.restoreUploaded"));
        setRestoreConfirm(false);
        setRestoreFile(null);
        if (restoreInputRef.current) restoreInputRef.current.value = "";
      } else {
        toast.error(j.error || t("settings.backup.restoreFailed"));
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  };

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
      cost_per_kwh: s.cost_per_kwh ?? null,
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
    // 04-W2-02: ALWAYS include cost_per_kwh — explicit null clears the tariff
    // (backend distinguishes omitted vs null via exclude_unset).
    payload.cost_per_kwh = editForm.cost_per_kwh;
    try {
      await put(`/api/servers/${id}`, payload);
      toast.success(t("settings.serverUpdated"));
      // 04-W4-02: warn when saving an unsupported vendor on a FanPilot-enabled server.
      // FanPilot only drives dell/supermicro fans; hpe/generic raise NotImplementedError
      // on the backend. fanpilot_enabled isn't in the edit form, so read it from the
      // just-saved server row (string id match — Decision C).
      const UNSUPPORTED_VENDORS = ["hpe", "generic"];
      const vendor = (editForm.vendor || "").toLowerCase();
      const savedServer = servers.find((srv) => srv.id === id);
      if (savedServer?.fanpilot_enabled && UNSUPPORTED_VENDORS.includes(vendor)) {
        toast.warning(t("settings.fanpilotVendorUnsupported", { vendor }), { duration: 6000 });
      }
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

  // Blocker #2 (D-13): App.tsx now routes /settings/* here. When the path is exactly
  // /settings (no section), redirect to the default landing section so bare-/settings
  // call-sites (Sidebar/MobileNavDrawer/CommandPalette/Dashboard) land populated. The
  // full two-pane + per-section routing is built in 06-08; for now any /settings/<section>
  // path falls through to the existing monolith as a single-panel passthrough.
  // (All hooks above run unconditionally — this early return is after them.)
  if (location.pathname === "/settings" || location.pathname === "/settings/") {
    return <Navigate replace to="/settings/servers" />;
  }

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
                        {/* 04-W2-02: per-server energy tariff. Id + ref are the anchor target
                            for 04-03's "Configura tariffa" CTA (#server-{id}-cost). */}
                        <div>
                          <label htmlFor={`server-${s.id}-cost`} className="mb-1 block text-xs font-medium text-muted-foreground">
                            {t("settings.costPerKwh")}
                          </label>
                          <input
                            id={`server-${s.id}-cost`}
                            ref={costInputRef}
                            type="number"
                            step="0.001"
                            min="0"
                            placeholder="0.350"
                            value={editForm.cost_per_kwh ?? ""}
                            onChange={(e) => setEditForm({
                              ...editForm,
                              cost_per_kwh: e.target.value === "" ? null : Number(e.target.value),
                            })}
                            className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm font-mono"
                          />
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

          {/* FanPilot (04-W1-01) — auto-recover on BMC offline. Placed between
              Servers and Security per UI-SPEC card placement order. */}
          <section className="rounded-lg border border-border bg-card p-5">
            <div className="mb-4 flex items-center gap-2">
              <Fan className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                {t("settings.fanpilot.title")}
              </h2>
            </div>
            <div className="flex items-center justify-between gap-3">
              <div className="flex-1">
                <label
                  id="fanpilot-auto-recover-label"
                  className="text-sm font-medium text-foreground"
                >
                  {t("settings.fanpilot.autoRecoverLabel")}
                </label>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t("settings.fanpilot.autoRecoverHint")}
                </p>
              </div>
              {/* Toggle switch (UI-SPEC: introduced in Phase 4; will be the
                  canonical toggle going forward). 44×44 tap-floor below md:
                  for mobile per UI-SPEC Mobile Contract. */}
              <button
                type="button"
                role="switch"
                aria-checked={autoRecover}
                aria-labelledby="fanpilot-auto-recover-label"
                onClick={toggleAutoRecover}
                disabled={fanpilotSaving || !online}
                title={offlineTip}
                className={cn(
                  "relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors min-h-11 min-w-11 md:min-h-5 md:min-w-9 items-center disabled:cursor-not-allowed disabled:opacity-50",
                  autoRecover ? "bg-emerald-500" : "bg-muted",
                )}
              >
                <span
                  className={cn(
                    "pointer-events-none inline-block h-4 w-4 transform rounded-full bg-background shadow ring-0 transition",
                    autoRecover ? "translate-x-4" : "translate-x-0",
                  )}
                />
              </button>
            </div>

            {/* quick-260626-4px: Resume threshold (hours; persisted as seconds).
                Store + expose only — consumed by Phase 5 startup-resume (inert now). */}
            <div className="mt-4 border-t border-border pt-4">
              <div className="mb-2 flex items-center justify-between">
                <label htmlFor="fanpilot-resume-threshold" className="text-sm font-medium text-foreground">
                  {t("settings.fanpilot.resumeThresholdLabel")}
                </label>
                <span className="font-mono text-sm tabular-nums">{resumeHours}</span>
              </div>
              <input
                id="fanpilot-resume-threshold"
                type="number"
                min={0}
                step={0.5}
                value={resumeHours}
                onChange={(e) => setResumeHours(Math.max(0, Number(e.target.value)))}
                disabled={!online}
                title={offlineTip}
                className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm disabled:opacity-50"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                {t("settings.fanpilot.resumeThresholdHint")}
              </p>
              <button
                type="button"
                onClick={onSaveResumeThreshold}
                disabled={resumeHours === resumeSavedHours || !online}
                title={offlineTip}
                className="mt-2 min-h-9 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50"
              >
                {t("settings.save")}
              </button>
            </div>

            {/* quick-260626-4px: Fail-safe behavior — BMC auto vs Fixed speed. Wired
                LIVE into offline/stale recovery. Default Fixed @ 100% (fail to full speed). */}
            <div className="mt-4 border-t border-border pt-4">
              <label id="fanpilot-failsafe-label" className="text-sm font-medium text-foreground">
                {t("settings.fanpilot.failsafeLabel")}
              </label>
              <p className="mt-1 text-xs text-muted-foreground">
                {t("settings.fanpilot.failsafeHint")}
              </p>
              <div
                role="radiogroup"
                aria-labelledby="fanpilot-failsafe-label"
                className="mt-3 flex gap-2"
              >
                <button
                  type="button"
                  role="radio"
                  aria-checked={failsafeMode === "fixed"}
                  onClick={() => onSelectFailsafeMode("fixed")}
                  disabled={fanpilotSaving || !online}
                  title={offlineTip}
                  className={cn(
                    "min-h-9 flex-1 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                    failsafeMode === "fixed"
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-background text-muted-foreground",
                  )}
                >
                  {t("settings.fanpilot.failsafeModeFixed")}
                </button>
                <button
                  type="button"
                  role="radio"
                  aria-checked={failsafeMode === "bmc_auto"}
                  onClick={() => onSelectFailsafeMode("bmc_auto")}
                  disabled={fanpilotSaving || !online}
                  title={offlineTip}
                  className={cn(
                    "min-h-9 flex-1 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                    failsafeMode === "bmc_auto"
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-background text-muted-foreground",
                  )}
                >
                  {t("settings.fanpilot.failsafeModeBmcAuto")}
                </button>
              </div>

              {failsafeMode === "fixed" && (
                <div className="mt-3">
                  <div className="mb-2 flex items-center justify-between">
                    <label htmlFor="fanpilot-failsafe-speed" className="text-sm font-medium text-foreground">
                      {t("settings.fanpilot.failsafeSpeedLabel")}
                    </label>
                    <span className="font-mono text-sm tabular-nums">{failsafeSpeed}%</span>
                  </div>
                  <input
                    id="fanpilot-failsafe-speed"
                    type="range"
                    min={0}
                    max={100}
                    step={1}
                    value={failsafeSpeed}
                    onChange={(e) => setFailsafeSpeed(Number(e.target.value))}
                    disabled={!online}
                    title={offlineTip}
                    className="h-2 w-full appearance-none rounded-lg bg-muted accent-foreground disabled:opacity-50"
                  />
                  <button
                    type="button"
                    onClick={onSaveFailsafeSpeed}
                    disabled={failsafeSpeed === failsafeSpeedSaved || !online}
                    title={offlineTip}
                    className="mt-2 min-h-9 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50"
                  >
                    {t("settings.save")}
                  </button>
                </div>
              )}
            </div>
          </section>

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

          {/* Alerting (04-W3-01) — browser-notifications opt-in. Placed between
              Security and Energy Counters per UI-SPEC card placement order. */}
          <section className="rounded-lg border border-border bg-card p-5">
            <div className="mb-4 flex items-center gap-2">
              <Bell className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                {t("settings.alerting.title")}
              </h2>
            </div>

            <div className="flex items-center justify-between gap-3">
              <div className="flex-1">
                <label id="alerting-notif-label" className="text-sm font-medium text-foreground">
                  {t("settings.alerting.enableNotifications")}
                </label>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t("settings.alerting.enableNotificationsHint")}
                </p>
              </div>
              {/* requestPermission MUST run inside this click handler (store.enable()) —
                  44×44 tap-floor below md: per UI-SPEC Mobile Contract. */}
              <button
                type="button"
                role="switch"
                aria-checked={notificationsEnabled}
                aria-labelledby="alerting-notif-label"
                onClick={async () => {
                  if (notificationsEnabled) {
                    await disableAlerting();
                  } else {
                    const perm = await enableAlerting();
                    if (perm === "denied") {
                      toast.error(t("settings.alerting.permissionDenied"));
                    } else if (perm === "granted") {
                      toast.success(t("settings.alerting.permissionGranted"));
                    }
                  }
                }}
                className={cn(
                  "relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors min-h-11 min-w-11 md:min-h-5 md:min-w-9 items-center",
                  notificationsEnabled ? "bg-emerald-500" : "bg-muted",
                )}
              >
                <span
                  className={cn(
                    "pointer-events-none inline-block h-4 w-4 transform rounded-full bg-background shadow ring-0 transition",
                    notificationsEnabled ? "translate-x-4" : "translate-x-0",
                  )}
                />
              </button>
            </div>

            <p className="mt-3 text-xs text-muted-foreground">
              {permission === "granted" && t("settings.alerting.permissionGranted")}
              {permission === "denied" && t("settings.alerting.permissionDenied")}
              {permission === "default" && t("settings.alerting.permissionPending")}
              {permission === "unsupported" && t("settings.alerting.permissionUnsupported")}
            </p>

            <p className="mt-2 text-xs text-muted-foreground">
              {t("settings.alerting.severityFilter")}
            </p>
          </section>

          {/* Energy Counters (04-W2-07) — per-server + reset-all energy counters.
              Placed after Security per UI-SPEC card order (Alerting/Data land in
              later plans; until then this sits between Security and Appearance). */}
          <section className="rounded-lg border border-border bg-card p-5">
            <div className="mb-4 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Zap className="h-4 w-4 text-violet-400" aria-hidden="true" />
                <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                  {t("settings.energy.title")}
                </h2>
              </div>
              <button
                type="button"
                onClick={() => setResetAllConfirm(true)}
                disabled={servers.length === 0}
                className="rounded-md border border-border px-2.5 py-1 text-xs font-medium text-red-500 hover:bg-red-500/10 min-h-11 md:min-h-9 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {t("settings.energy.resetAll")}
              </button>
            </div>

            {/* Reset-all inline confirm (destructive contract — Security disable pattern). */}
            {resetAllConfirm && (
              <div className="mb-4 space-y-3 rounded-md border border-red-500/30 bg-red-500/5 p-3">
                <p className="text-xs text-muted-foreground">
                  {t("settings.energy.confirmResetAllBody", { count: servers.length })}
                </p>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setResetAllConfirm(false)}
                    className="flex-1 rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground min-h-11 md:min-h-9"
                  >
                    {t("settings.cancel")}
                  </button>
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        await resetAll();
                        setResetAllConfirm(false);
                        toast.success(t("settings.energy.resetSuccess"));
                      } catch {
                        toast.error(t("settings.energy.resetFailed"));
                      }
                    }}
                    className="flex-1 rounded-md bg-red-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-red-600 min-h-11 md:min-h-9"
                  >
                    {t("settings.energy.confirmResetAll")}
                  </button>
                </div>
              </div>
            )}

            {servers.length === 0 ? (
              <p className="text-xs text-muted-foreground">{t("settings.noServersDescription")}</p>
            ) : (
              <div className="space-y-2">
                {servers.map((server) => (
                  <div
                    key={server.id}
                    className="flex flex-col items-stretch justify-between gap-3 rounded-md border border-border p-3 md:flex-row md:items-center"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-foreground">{server.name}</div>
                      <div className="text-xs text-muted-foreground">
                        {resets[server.id]
                          ? t("settings.energy.lastReset", {
                              value: new Date(resets[server.id]!).toLocaleString(energyLocale),
                            })
                          : t("settings.energy.neverReset")}
                      </div>
                    </div>
                    {resetConfirmId === server.id ? (
                      <div className="w-full space-y-3 rounded-md border border-red-500/30 bg-red-500/5 p-3 md:w-auto">
                        <p className="text-xs text-muted-foreground">
                          {t("settings.energy.confirmResetBody", { name: server.name })}
                        </p>
                        <div className="flex gap-2">
                          <button
                            type="button"
                            onClick={() => setResetConfirmId(null)}
                            className="flex-1 rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground min-h-11 md:min-h-9"
                          >
                            {t("settings.cancel")}
                          </button>
                          <button
                            type="button"
                            onClick={async () => {
                              try {
                                await resetServer(server.id);
                                setResetConfirmId(null);
                                toast.success(t("settings.energy.resetSuccess"));
                              } catch {
                                toast.error(t("settings.energy.resetFailed"));
                              }
                            }}
                            className="flex-1 rounded-md bg-red-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-red-600 min-h-11 md:min-h-9"
                          >
                            {t("settings.energy.confirmReset")}
                          </button>
                        </div>
                      </div>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setResetConfirmId(server.id)}
                        className="w-full rounded-md border border-border px-2.5 py-1 text-xs font-medium text-red-500 hover:bg-red-500/10 min-h-11 md:min-h-9 md:w-auto"
                      >
                        {t("settings.energy.resetServer", { name: server.name })}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* Data (04-W5-01) — retention slider + DB stats + immediate cleanup. Placed
              between Energy Counters and Network per UI-SPEC card placement order. */}
          <section className="rounded-lg border border-border bg-card p-5">
            <div className="mb-4 flex items-center gap-2">
              <Database className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                {t("settings.data.title")}
              </h2>
            </div>

            <div className="space-y-4">
              {/* Retention slider */}
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <label htmlFor="retention-days" className="text-sm font-medium text-foreground">
                    {t("settings.data.retentionLabel")}
                  </label>
                  <span className="font-mono text-sm tabular-nums">{retentionDays}</span>
                </div>
                <input
                  id="retention-days"
                  type="range"
                  min={7}
                  max={365}
                  step={1}
                  value={retentionDays}
                  onChange={(e) => setRetentionDays(Number(e.target.value))}
                  disabled={!online}
                  className="h-2 w-full appearance-none rounded-lg bg-muted accent-foreground disabled:opacity-50"
                />
                <p className="mt-1 text-xs text-muted-foreground">{t("settings.data.retentionHint")}</p>
                <button
                  type="button"
                  onClick={onSaveRetention}
                  disabled={retentionDays === retentionSaved || !online}
                  title={offlineTip}
                  className="mt-2 min-h-9 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50"
                >
                  {t("settings.save")}
                </button>
              </div>

              {/* DB stats readout */}
              <div className="space-y-1.5 border-t border-border pt-4">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">{t("settings.data.dbSize")}</span>
                  <span className="font-mono">{formatBytes(dbStats.db_size_bytes)}</span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">{t("settings.data.rowCount")}</span>
                  <span className="font-mono">{dbStats.sensor_readings_rows.toLocaleString(dataLocale)}</span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">{t("settings.data.oldestReading")}</span>
                  <span className="font-mono">
                    {dbStats.oldest_reading_timestamp
                      ? new Date(dbStats.oldest_reading_timestamp).toLocaleString(dataLocale)
                      : "—"}
                  </span>
                </div>
              </div>

              {/* Run cleanup now — inline confirm (destructive, red treatment) */}
              <div className="border-t border-border pt-4">
                {cleanupConfirm ? (
                  <div className="space-y-3 rounded-md border border-red-500/30 bg-red-500/5 p-3">
                    <p className="text-xs text-muted-foreground">
                      {t("settings.data.confirmCleanupBody", { days: retentionDays })}
                    </p>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => setCleanupConfirm(false)}
                        className="min-h-11 flex-1 rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground md:min-h-9"
                      >
                        {t("settings.cancel")}
                      </button>
                      <button
                        type="button"
                        onClick={onRunCleanup}
                        disabled={cleanupBusy || !online}
                        className="min-h-11 flex-1 rounded-md bg-red-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-red-600 disabled:opacity-50 md:min-h-9"
                      >
                        {t("settings.data.confirmCleanup")}
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setCleanupConfirm(true)}
                    disabled={!online}
                    title={offlineTip}
                    className="min-h-9 rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:opacity-50"
                  >
                    {t("settings.data.runCleanup")}
                  </button>
                )}
              </div>
            </div>
          </section>

          {/* Network (04-W4-03) — HTTPS toggle + self-signed cert generation. Placed
              among the infra Settings cards (after Energy Counters; Data/Backup land in
              later plans) per UI-SPEC card placement order. */}
          <section className="rounded-lg border border-border bg-card p-5">
            <div className="mb-4 flex items-center gap-2">
              <Lock className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                {t("settings.network.title")}
              </h2>
            </div>

            {/* HTTPS toggle row */}
            <div className="mb-4 flex items-center justify-between gap-3">
              <div className="flex-1">
                <label id="https-label" className="text-sm font-medium text-foreground">
                  {t("settings.network.httpsLabel")}
                </label>
                <p className="mt-1 text-xs text-muted-foreground">{t("settings.network.httpsHint")}</p>
              </div>
              {/* 44×44 tap-floor below md: per UI-SPEC Mobile Contract. */}
              <button
                type="button"
                role="switch"
                aria-checked={https}
                aria-labelledby="https-label"
                onClick={onToggleHttps}
                disabled={networkBusy || !online}
                title={offlineTip}
                className={cn(
                  "relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors min-h-11 min-w-11 md:min-h-5 md:min-w-9 disabled:cursor-not-allowed disabled:opacity-50",
                  https ? "bg-emerald-500" : "bg-muted",
                )}
              >
                <span
                  className={cn(
                    "pointer-events-none inline-block h-4 w-4 transform rounded-full bg-background shadow ring-0 transition",
                    https ? "translate-x-4" : "translate-x-0",
                  )}
                />
              </button>
            </div>

            {/* Confirm banner when enabling (restart + self-signed warning). */}
            {httpsConfirm && !https && (
              <div className="mb-4 space-y-3 rounded-md border border-yellow-500/30 bg-yellow-500/5 p-3">
                <p className="text-xs text-muted-foreground">{t("settings.network.selfSignedNote")}</p>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setHttpsConfirm(false)}
                    className="flex-1 rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground min-h-11 md:min-h-9"
                  >
                    {t("settings.cancel")}
                  </button>
                  <button
                    type="button"
                    onClick={onToggleHttps}
                    disabled={networkBusy || !online}
                    title={offlineTip}
                    className="flex-1 rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground min-h-11 md:min-h-9 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {t("settings.network.confirmHttps")}
                  </button>
                </div>
              </div>
            )}

            {/* Cert + key paths (read-only — populated by the generate action). */}
            <div className="mb-4 space-y-3">
              <div>
                <label htmlFor="cert-path" className="mb-1 block text-xs font-medium text-muted-foreground">
                  {t("settings.network.certPath")}
                </label>
                <input
                  id="cert-path"
                  type="text"
                  value={certPath}
                  readOnly
                  placeholder="data/certs/server.crt"
                  className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm font-mono min-h-11 md:min-h-9"
                />
              </div>
              <div>
                <label htmlFor="key-path" className="mb-1 block text-xs font-medium text-muted-foreground">
                  {t("settings.network.keyPath")}
                </label>
                <input
                  id="key-path"
                  type="text"
                  value={keyPath}
                  readOnly
                  placeholder="data/certs/server.key"
                  className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm font-mono min-h-11 md:min-h-9"
                />
              </div>
            </div>

            <button
              type="button"
              onClick={onGenCert}
              disabled={networkBusy || !online}
              title={offlineTip}
              className="rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-muted min-h-11 md:min-h-9 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {t("settings.network.genCertButton")}
            </button>

            {/* Yellow warning banner (always visible — UI-SPEC contract). */}
            <div className="mt-4 rounded-md border border-yellow-500/30 bg-yellow-500/5 p-3 text-xs text-yellow-600 dark:text-yellow-500">
              {t("settings.network.selfSignedNote")}
            </div>
          </section>

          {/* Backup & Restore (04-W6-03) — zip download + upload-restore. Placed after
              Network per UI-SPEC card order. Restore behind an inline red confirm. */}
          <section className="rounded-lg border border-border bg-card p-5">
            <div className="mb-4 flex items-center gap-2">
              <Archive className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                {t("settings.backup.title")}
              </h2>
            </div>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div className="space-y-2">
                <button
                  type="button"
                  onClick={onDownloadBackup}
                  disabled={!online}
                  title={offlineTip}
                  className="w-full rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground min-h-11 md:min-h-9 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {t("settings.backup.downloadBackup")}
                </button>
                <p className="text-xs text-muted-foreground">{t("settings.backup.downloadHint")}</p>
              </div>

              <div className="space-y-2">
                <input
                  ref={restoreInputRef}
                  type="file"
                  accept=".zip"
                  onChange={(e) => setRestoreFile(e.target.files?.[0] ?? null)}
                  className="w-full text-xs text-muted-foreground file:mr-2 file:rounded-md file:border file:border-border file:bg-background file:px-2 file:py-1 file:text-xs file:text-foreground"
                />
                {restoreFile && !restoreConfirm && (
                  <button
                    type="button"
                    onClick={() => setRestoreConfirm(true)}
                    className="w-full rounded-md border border-border px-3 py-1.5 text-sm font-medium text-red-500 min-h-11 md:min-h-9 hover:bg-muted"
                  >
                    {t("settings.backup.uploadRestore")}
                  </button>
                )}
                {restoreConfirm && (
                  <div className="space-y-3 rounded-md border border-red-500/30 bg-red-500/5 p-3">
                    <p className="text-xs text-muted-foreground">{t("settings.backup.confirmRestoreBody")}</p>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => setRestoreConfirm(false)}
                        className="flex-1 rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground min-h-11 md:min-h-9"
                      >
                        {t("settings.cancel")}
                      </button>
                      <button
                        type="button"
                        onClick={onRestore}
                        className="flex-1 rounded-md bg-red-500 px-3 py-1.5 text-sm font-semibold text-white min-h-11 md:min-h-9 hover:bg-red-600"
                      >
                        {t("settings.backup.confirmRestore")}
                      </button>
                    </div>
                  </div>
                )}
                <p className="text-xs text-muted-foreground">{t("settings.backup.restoreHint")}</p>
              </div>
            </div>
          </section>

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
            <div className="mt-4 flex items-center justify-between gap-3" data-tour="language-select">
              <span className="text-sm font-medium">{t("settings.language")}</span>
              <LanguageSelect className="rounded-md border border-border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50" />
            </div>
            {/* 04-W2-03: global currency — auto-derived from language once on first run,
                then user-controlled. Native <select> with "€ EUR" labels per UI-SPEC. */}
            <div className="mt-4 flex items-center justify-between gap-3">
              <label htmlFor="currency-select" className="text-sm font-medium">
                {t("settings.currency.label")}
              </label>
              <select
                id="currency-select"
                value={currency}
                onChange={(e) => setCurrency(e.target.value as CurrencyCode)}
                className="rounded-md border border-border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
              >
                {SUPPORTED_CURRENCIES.map((c) => (
                  <option key={c} value={c}>{currencyOptionLabel(c)}</option>
                ))}
              </select>
            </div>
            {/* Replay onboarding tour (UX-02 / D-03): re-runs the guided tour anytime. */}
            <div className="mt-4 flex items-center justify-between gap-3">
              <span className="text-sm font-medium">{t("tour.replay")}</span>
              <button
                onClick={startTour}
                className="rounded-md border border-border px-3 py-1.5 text-sm font-medium transition-colors hover:bg-muted"
              >
                {t("tour.replay")}
              </button>
            </div>
          </div>

          {/* About */}
          <div className="rounded-lg border border-border bg-card p-5">
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-muted-foreground">{t("settings.about.title")}</h2>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">{t("settings.version")}</span>
                <span className="font-mono text-sm">{appVersion ?? "—"}</span>
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
                    <a href="https://luigitanzillo.it/" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground">
                      <Globe className="h-3 w-3" /> luigitanzillo.it <ExternalLink className="h-2.5 w-2.5" />
                    </a>
                    <a href="https://github.com/sponsors/dev-luigi" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded-md border border-pink-500/30 bg-pink-500/10 px-2 py-0.5 text-[11px] font-medium text-pink-400 transition-colors hover:bg-pink-500/20">
                      <Heart className="h-3 w-3 fill-current" /> {t("settings.sponsor")} <ExternalLink className="h-2.5 w-2.5" />
                    </a>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
