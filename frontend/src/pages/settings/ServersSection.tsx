import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import { Plus, Trash2, TestTube, Pencil, Fan, Wifi, WifiOff } from "lucide-react";
import { useServerStore, type Server } from "@/stores/server-store";
import { get, post, put, del } from "@/api/client";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/common/EmptyState";
import { Server as ServerIcon } from "lucide-react";
import { VENDORS, TIER_LABEL_KEY, isFanCapable, VENDOR_VALUES } from "@/lib/vendors";
import { useSettings } from "./SettingsContext";
import {
  SectionPanel,
  FieldGroup,
  inputClass,
  primaryBtnClass,
  secondaryBtnClass,
} from "./primitives";

interface ServersSectionProps {
  headingRef: React.Ref<HTMLHeadingElement>;
}

// Derived from the single source of truth (@/lib/vendors) so the six canonical
// vendors + their tier/capability never drift from the Setup wizard or the backend.
const VENDOR_OPTIONS = VENDOR_VALUES;

/**
 * Servers section — BMC CRUD, credentials, test, per-server tariff (costPerKwh),
 * and FanPilot auto-recover (D-13 brief §5). DEFAULT landing section.
 *
 * Blocker #1 deep-link: the SHELL owns the hash match + navigation to
 * /settings/servers (so the panel is guaranteed mounted); this section owns the
 * one-shot edit-open + cost-input focus, because startEdit + the form state it
 * prefills live here. The shell never reaches into a section's state. The regex
 * `^#server-(.+)-cost$` and the input id `server-${id}-cost` are preserved
 * verbatim; the undefined/new guards are preserved.
 */
export function ServersSection({ headingRef }: ServersSectionProps) {
  const { t } = useTranslation();
  const { online, offlineTip } = useSettings();
  const { servers, setServers } = useServerStore();
  const location = useLocation();
  const navigate = useNavigate();

  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", host: "", username: "", password: "", vendor: "dell" });
  const [testing, setTesting] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState({ name: "", description: "", host: "", username: "", password: "", vendor: "dell", cost_per_kwh: null as number | null });
  // 04-W2-02: ref on the cost input — reused by the "Configura tariffa" CTA
  // (hash navigation /settings#server-{id}-cost scrolls + focuses this field).
  const costInputRef = useRef<HTMLInputElement>(null);

  // 04-W1-01: FanPilot auto-recover on BMC offline (persisted in app_config).
  const [autoRecover, setAutoRecover] = useState(true);
  const [fanpilotSaving, setFanpilotSaving] = useState(false);
  // quick-260626-4px: resume threshold (hours; persisted as seconds).
  const [resumeHours, setResumeHours] = useState(1);
  const [resumeSavedHours, setResumeSavedHours] = useState(1);
  // quick-260626-4px: fail-safe behavior — BMC auto vs Fixed speed.
  const [failsafeMode, setFailsafeMode] = useState<"bmc_auto" | "fixed">("fixed");
  const [failsafeSpeed, setFailsafeSpeed] = useState(100);
  const [failsafeSpeedSaved, setFailsafeSpeedSaved] = useState(100);

  const loadServers = async () => {
    try {
      const data = await get<{ servers: Server[] }>("/api/servers");
      setServers(data.servers);
    } catch { /* ignore */ }
  };

  useEffect(() => { loadServers(); }, []);

  // Load the FanPilot config (auto-recover / resume / failsafe).
  useEffect(() => {
    get<{ success: boolean; key: string; value: boolean | null }>(
      "/api/system/app-config/fanpilot.auto_recover_on_offline"
    )
      .then((r) => { if (r.value !== null && r.value !== undefined) setAutoRecover(Boolean(r.value)); })
      .catch(() => { /* default ON */ });
    get<{ success: boolean; key: string; value: number | string | null }>(
      "/api/system/app-config/fanpilot.resume_threshold_seconds"
    )
      .then((r) => {
        if (r.value !== null && r.value !== undefined && r.value !== "") {
          const secs = Number(r.value);
          if (!Number.isNaN(secs)) { const hrs = secs / 3600; setResumeHours(hrs); setResumeSavedHours(hrs); }
        }
      })
      .catch(() => { /* default 1h */ });
    get<{ success: boolean; key: string; value: number | string | null }>(
      "/api/system/app-config/fanpilot.failsafe_mode"
    )
      .then((r) => { if (r.value === "bmc_auto" || r.value === "fixed") setFailsafeMode(r.value); })
      .catch(() => { /* default fixed */ });
    get<{ success: boolean; key: string; value: number | string | null }>(
      "/api/system/app-config/fanpilot.failsafe_speed"
    )
      .then((r) => {
        if (r.value !== null && r.value !== undefined && r.value !== "") {
          const n = Number(r.value);
          if (!Number.isNaN(n)) { const c = Math.min(100, Math.max(0, Math.round(n))); setFailsafeSpeed(c); setFailsafeSpeedSaved(c); }
        }
      })
      .catch(() => { /* default 100 */ });
  }, []);

  const startEdit = (s: Server) => {
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

  // Blocker #1 deep-link consumer. The shell has already navigated us to
  // /settings/servers preserving the hash; here we open the edit form for the
  // target server and focus the cost input, then clear the hash. Regex + input
  // id + undefined/new guards preserved VERBATIM (04-W2-04 / GAP-B / Decision C).
  useEffect(() => {
    const match = location.hash.match(/^#server-(.+)-cost$/);
    if (!match) return;
    const targetId = match[1]; // string — Decision C, no Number()/parseInt
    if (!targetId || targetId === "undefined" || targetId === "new") return;
    const target = useServerStore.getState().servers.find((s) => s.id === targetId);
    if (target == null) return;
    if (editingId !== targetId) startEdit(target);
    // waitForEl: poll for the cost input (the edit form renders on the next tick).
    let frame = 0;
    let attempts = 0;
    const poll = () => {
      const el = document.getElementById(`server-${targetId}-cost`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        (el as HTMLInputElement).focus();
        navigate(location.pathname + location.search, { replace: true });
        return;
      }
      if (attempts++ < 30) frame = requestAnimationFrame(poll);
    };
    frame = requestAnimationFrame(poll);
    return () => cancelAnimationFrame(frame);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one-shot deep-link prefill;
    // re-running on editingId/startEdit identity would re-fire scroll/focus on every keystroke.
  }, [location.hash, location.pathname, location.search, navigate]);

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

  const saveEdit = async (id: string) => {
    if (!editForm.host.trim()) {
      toast.error(t("settings.hostRequired"));
      return;
    }
    const payload: Record<string, unknown> = {
      name: editForm.name,
      description: editForm.description,
      host: editForm.host,
      vendor: editForm.vendor,
    };
    if (editForm.username.trim()) payload.username = editForm.username;
    if (editForm.password.trim()) payload.password = editForm.password;
    payload.cost_per_kwh = editForm.cost_per_kwh;
    try {
      await put(`/api/servers/${id}`, payload);
      toast.success(t("settings.serverUpdated"));
      // D-13 warn-but-allow: any monitoring-only (fanCapable=false) vendor warns —
      // derived from @/lib/vendors so hpe/lenovo/generic ALL warn (fixes the old
      // hardcoded unsupported-vendor list that missed 'hp'/'lenovo'). No hard block.
      const vendor = (editForm.vendor || "").toLowerCase();
      const savedServer = servers.find((srv) => srv.id === id);
      if (savedServer?.fanpilot_enabled && !isFanCapable(vendor)) {
        toast.warning(t("settings.fanpilotVendorUnsupported", { vendor }), { duration: 6000 });
      }
      setEditingId(null);
      await loadServers();
    } catch {
      toast.error(t("settings.serverUpdateFailed"));
    }
  };

  const openAddForm = () => {
    setShowForm((prev) => {
      const next = !prev;
      if (next) setEditingId(null);
      return next;
    });
  };

  // FanPilot config mutations.
  const toggleAutoRecover = async () => {
    const next = !autoRecover;
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

  const onSaveResumeThreshold = async () => {
    try {
      await put("/api/system/app-config/fanpilot.resume_threshold_seconds", { value: Math.round(resumeHours * 3600) });
      setResumeSavedHours(resumeHours);
      toast.success(t("settings.fanpilot.resumeThresholdSaved"));
    } catch {
      toast.error(t("settings.fanpilot.saveFailed"));
    }
  };

  const onSelectFailsafeMode = async (mode: "bmc_auto" | "fixed") => {
    if (mode === failsafeMode) return;
    const prev = failsafeMode;
    setFailsafeMode(mode);
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

  const renderServerForm = (
    f: typeof form | typeof editForm,
    set: (next: any) => void,
    opts: { edit?: boolean; serverId?: string } = {},
  ) => (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <input placeholder={t("settings.namePlaceholder")} value={f.name} onChange={(e) => set({ ...f, name: e.target.value })} className={inputClass} />
      <input placeholder={t("settings.descriptionPlaceholder")} value={f.description} onChange={(e) => set({ ...f, description: e.target.value })} className={inputClass} />
      <input placeholder={t("settings.hostPlaceholder")} value={f.host} onChange={(e) => set({ ...f, host: e.target.value })} className={inputClass} />
      <select value={f.vendor} onChange={(e) => set({ ...f, vendor: e.target.value })} className={inputClass}>
        {VENDORS.map((v) => (
          <option key={v.value} value={v.value}>
            {`${t(v.labelKey)} — ${t(TIER_LABEL_KEY[v.tier])}`}
          </option>
        ))}
      </select>
      <input placeholder={opts.edit ? t("settings.editUsernamePlaceholder") : t("settings.usernamePlaceholder")} value={f.username} onChange={(e) => set({ ...f, username: e.target.value })} className={inputClass} />
      <input type="password" placeholder={opts.edit ? t("settings.editPasswordPlaceholder") : t("settings.passwordPlaceholder")} value={f.password} onChange={(e) => set({ ...f, password: e.target.value })} className={cn(inputClass, "font-mono")} />
    </div>
  );

  return (
    <SectionPanel
      ref={headingRef}
      headingId="settings-panel-heading"
      title={t("settings.servers")}
      description={t("settings.sections.serversDescription")}
      action={
        <button
          onClick={openAddForm}
          disabled={!online}
          title={offlineTip}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground min-h-[--control-min] md:min-h-9 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus className="h-4 w-4" /> {t("settings.add")}
        </button>
      }
    >
      <FieldGroup title={t("settings.servers")} description={t("settings.sections.serversConnectionsHint")}>
        {showForm && (
          <div className="mb-4 space-y-3 rounded-md border border-border bg-muted/40 p-4">
            {renderServerForm(form, setForm)}
            <div className="flex justify-end gap-2">
              <button onClick={() => setShowForm(false)} className={secondaryBtnClass}>{t("settings.cancel")}</button>
              <button onClick={addServer} disabled={!online} title={offlineTip} className={primaryBtnClass}>
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
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{s.name}</div>
                    <div className="truncate font-mono text-xs text-muted-foreground">{s.host}</div>
                  </div>
                  {/* Status — triple-encoded (color + icon shape + text label) so it
                      is not color-only for colorblind operators (D-04). */}
                  <span
                    className={cn(
                      "inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
                      s.is_online ? "bg-success/10 text-success" : "bg-danger/10 text-danger",
                    )}
                  >
                    {s.is_online
                      ? <Wifi className="h-3 w-3" aria-hidden="true" />
                      : <WifiOff className="h-3 w-3" aria-hidden="true" />}
                    <span>{s.is_online ? t("settings.aria.serverOnline") : t("settings.aria.serverOffline")}</span>
                  </span>
                  <div className="flex gap-1">
                    <button onClick={() => startEdit(s)} aria-label={t("settings.aria.editServer")} className="rounded-md border border-border p-2 hover:bg-muted min-h-[--control-min] min-w-[--control-min] md:min-h-9 md:min-w-9 inline-flex items-center justify-center">
                      <Pencil className="h-4 w-4" />
                    </button>
                    <button
                      onClick={() => testServer(s.id)}
                      disabled={testing === s.id || !online}
                      title={offlineTip}
                      aria-label={t("settings.aria.testConnection")}
                      className="rounded-md border border-border p-2 hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 min-h-[--control-min] min-w-[--control-min] md:min-h-9 md:min-w-9 inline-flex items-center justify-center"
                    >
                      <TestTube className={cn("h-4 w-4", testing === s.id && "animate-spin")} />
                    </button>
                    <button
                      onClick={() => deleteServer(s.id)}
                      disabled={!online}
                      title={offlineTip}
                      aria-label={t("settings.aria.deleteServer")}
                      className="rounded-md border border-border p-2 text-danger hover:bg-danger/10 disabled:cursor-not-allowed disabled:opacity-50 min-h-[--control-min] min-w-[--control-min] md:min-h-9 md:min-w-9 inline-flex items-center justify-center"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>

                {editingId === s.id && (
                  <div className="mt-2 space-y-3 rounded-md border border-border bg-muted/40 p-4">
                    {renderServerForm(editForm, setEditForm, { edit: true, serverId: s.id })}
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
                        onChange={(e) => setEditForm({ ...editForm, cost_per_kwh: e.target.value === "" ? null : Number(e.target.value) })}
                        className={cn(inputClass, "font-mono")}
                      />
                    </div>
                    <div className="flex justify-end gap-2">
                      <button onClick={() => setEditingId(null)} className={secondaryBtnClass}>{t("settings.discardChanges")}</button>
                      <button onClick={() => saveEdit(s.id)} disabled={!online} title={offlineTip} className={primaryBtnClass}>
                        {t("settings.saveChanges")}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </FieldGroup>

      {/* FanPilot — auto-recover, resume threshold, fail-safe behavior. */}
      <FieldGroup
        title={t("settings.fanpilot.title")}
        action={<Fan className="h-4 w-4 text-cyan" aria-hidden="true" />}
      >
        <div className="flex items-center justify-between gap-3">
          <div className="flex-1">
            <label id="fanpilot-auto-recover-label" className="text-sm font-medium text-foreground">
              {t("settings.fanpilot.autoRecoverLabel")}
            </label>
            <p className="mt-1 text-xs text-muted-foreground">{t("settings.fanpilot.autoRecoverHint")}</p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={autoRecover}
            aria-labelledby="fanpilot-auto-recover-label"
            onClick={toggleAutoRecover}
            disabled={fanpilotSaving || !online}
            title={offlineTip}
            className={cn(
              "relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors min-h-[--control-min] min-w-[--control-min] md:min-h-6 md:min-w-11 disabled:cursor-not-allowed disabled:opacity-50",
              autoRecover ? "bg-success" : "bg-muted",
            )}
          >
            <span className={cn("pointer-events-none inline-block h-5 w-5 transform rounded-full bg-background shadow ring-0 transition", autoRecover ? "translate-x-5" : "translate-x-0")} />
          </button>
        </div>

        <div className="mt-4 border-t border-border/60 pt-4">
          <div className="mb-2 flex items-center justify-between">
            <label htmlFor="fanpilot-resume-threshold" className="text-sm font-medium text-foreground">{t("settings.fanpilot.resumeThresholdLabel")}</label>
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
            className={inputClass}
          />
          <p className="mt-1 text-xs text-muted-foreground">{t("settings.fanpilot.resumeThresholdHint")}</p>
          <button type="button" onClick={onSaveResumeThreshold} disabled={resumeHours === resumeSavedHours || !online} title={offlineTip} className={cn(primaryBtnClass, "mt-2")}>
            {t("settings.save")}
          </button>
        </div>

        <div className="mt-4 border-t border-border/60 pt-4">
          <label id="fanpilot-failsafe-label" className="text-sm font-medium text-foreground">{t("settings.fanpilot.failsafeLabel")}</label>
          <p className="mt-1 text-xs text-muted-foreground">{t("settings.fanpilot.failsafeHint")}</p>
          <div role="radiogroup" aria-labelledby="fanpilot-failsafe-label" className="mt-3 flex gap-2">
            {(["fixed", "bmc_auto"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                role="radio"
                aria-checked={failsafeMode === mode}
                onClick={() => onSelectFailsafeMode(mode)}
                disabled={fanpilotSaving || !online}
                title={offlineTip}
                className={cn(
                  "min-h-[--control-min] md:min-h-9 flex-1 rounded-md border px-3 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                  failsafeMode === mode ? "border-primary bg-primary text-primary-foreground" : "border-border bg-background text-muted-foreground hover:bg-muted",
                )}
              >
                {mode === "fixed" ? t("settings.fanpilot.failsafeModeFixed") : t("settings.fanpilot.failsafeModeBmcAuto")}
              </button>
            ))}
          </div>
          {failsafeMode === "fixed" && (
            <div className="mt-3">
              <div className="mb-2 flex items-center justify-between">
                <label htmlFor="fanpilot-failsafe-speed" className="text-sm font-medium text-foreground">{t("settings.fanpilot.failsafeSpeedLabel")}</label>
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
                className="h-2 w-full appearance-none rounded-lg bg-muted accent-primary disabled:opacity-50"
              />
              <button type="button" onClick={onSaveFailsafeSpeed} disabled={failsafeSpeed === failsafeSpeedSaved || !online} title={offlineTip} className={cn(primaryBtnClass, "mt-2")}>
                {t("settings.save")}
              </button>
            </div>
          )}
        </div>
      </FieldGroup>
    </SectionPanel>
  );
}

export { VENDOR_OPTIONS };
