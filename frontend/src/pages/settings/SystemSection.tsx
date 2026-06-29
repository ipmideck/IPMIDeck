import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Database, Lock, Archive, AlertTriangle } from "lucide-react";
import { get, post, put } from "@/api/client";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { useSettings } from "./SettingsContext";
import { SectionPanel, FieldGroup, formatBytes, inputClass, primaryBtnClass, secondaryBtnClass } from "./primitives";

interface SystemSectionProps {
  headingRef: React.Ref<HTMLHeadingElement>;
}

/**
 * System section — Data (retention/db-stats/cleanup) + Network (HTTPS/cert/
 * gen-cert) + Backup (download/restore). Three destructive 2-step confirms live
 * here (cleanup, HTTPS-enable, restore) — preserved verbatim.
 *
 * certPath/keyPath are read from the shell context (NOT section-local state) so
 * the generated paths survive navigating away from System and back (medium caveat).
 */
export function SystemSection({ headingRef }: SystemSectionProps) {
  const { t, i18n } = useTranslation();
  const { online, offlineTip, certPath, setCertPath, keyPath, setKeyPath } = useSettings();
  const dataLocale = i18n.resolvedLanguage || "en";

  // --- Data ---
  const [retentionDays, setRetentionDays] = useState(30);
  const [retentionSaved, setRetentionSaved] = useState(30);
  const [dbStats, setDbStats] = useState({ db_size_bytes: 0, sensor_readings_rows: 0, oldest_reading_timestamp: null as string | null });
  const [cleanupConfirm, setCleanupConfirm] = useState(false);
  const [cleanupBusy, setCleanupBusy] = useState(false);

  const refreshDbStats = async () => {
    try {
      const r = await get<{ success: boolean; db_size_bytes: number; sensor_readings_rows: number; oldest_reading_timestamp: string | null }>("/api/system/db-stats");
      if (r.success) {
        setDbStats({ db_size_bytes: r.db_size_bytes, sensor_readings_rows: r.sensor_readings_rows, oldest_reading_timestamp: r.oldest_reading_timestamp });
      }
    } catch { /* offline indicator handles connectivity */ }
  };

  useEffect(() => {
    get<{ success: boolean; days: number }>("/api/system/retention-days")
      .then((r) => { if (r.success) { setRetentionDays(r.days); setRetentionSaved(r.days); } })
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
      const r = await post<{ success: boolean; deleted_rows: number }>("/api/system/retention-cleanup-now");
      if (r.success) { toast.success(t("settings.data.cleanupDone")); setCleanupConfirm(false); await refreshDbStats(); }
    } catch (e: any) {
      toast.error(String(e?.message ?? e));
      setCleanupConfirm(false);
    } finally {
      setCleanupBusy(false);
    }
  };

  // --- Network ---
  const [https, setHttps] = useState(false);
  const [httpsConfirm, setHttpsConfirm] = useState(false);
  const [networkBusy, setNetworkBusy] = useState(false);

  const onGenCert = async () => {
    setNetworkBusy(true);
    try {
      const r = await post<{ success: boolean; cert_path?: string; key_path?: string; error?: string }>("/api/system/gen-cert");
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
    if (!https && !httpsConfirm) { setHttpsConfirm(true); return; }
    await applyHttps(!https);
  };

  // --- Backup & Restore ---
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

  return (
    <SectionPanel
      ref={headingRef}
      headingId="settings-panel-heading"
      title={t("settings.sections.system")}
      description={t("settings.sections.systemDescription")}
    >
      {/* Data */}
      <FieldGroup title={t("settings.data.title")} action={<Database className="h-4 w-4 text-muted-foreground" aria-hidden="true" />}>
        <div className="space-y-4">
          <div>
            <div className="mb-2 flex items-center justify-between">
              <label htmlFor="retention-days" className="text-sm font-medium text-foreground">{t("settings.data.retentionLabel")}</label>
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
              className="h-2 w-full appearance-none rounded-lg bg-muted accent-primary disabled:opacity-50"
            />
            <p className="mt-1 text-xs text-muted-foreground">{t("settings.data.retentionHint")}</p>
            <button type="button" onClick={onSaveRetention} disabled={retentionDays === retentionSaved || !online} title={offlineTip} className={cn(primaryBtnClass, "mt-2")}>
              {t("settings.save")}
            </button>
          </div>

          <div className="space-y-1.5 border-t border-border/60 pt-4">
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
              <span className="font-mono">{dbStats.oldest_reading_timestamp ? new Date(dbStats.oldest_reading_timestamp).toLocaleString(dataLocale) : "—"}</span>
            </div>
          </div>

          <div className="border-t border-border/60 pt-4">
            {cleanupConfirm ? (
              <div className="space-y-3 rounded-md border border-danger/30 bg-danger/5 p-3">
                <p className="text-xs text-muted-foreground">{t("settings.data.confirmCleanupBody", { days: retentionDays })}</p>
                <div className="flex gap-2">
                  <button type="button" onClick={() => setCleanupConfirm(false)} className={cn(secondaryBtnClass, "flex-1")}>{t("settings.cancel")}</button>
                  <button type="button" onClick={onRunCleanup} disabled={cleanupBusy || !online} className="flex-1 rounded-md bg-danger px-3 py-2 text-sm font-semibold text-white hover:bg-danger/90 min-h-[--control-min] md:min-h-9 disabled:opacity-50">
                    {t("settings.data.confirmCleanup")}
                  </button>
                </div>
              </div>
            ) : (
              <button type="button" onClick={() => setCleanupConfirm(true)} disabled={!online} title={offlineTip} className={secondaryBtnClass}>
                {t("settings.data.runCleanup")}
              </button>
            )}
          </div>
        </div>
      </FieldGroup>

      {/* Network */}
      <FieldGroup title={t("settings.network.title")} action={<Lock className="h-4 w-4 text-muted-foreground" aria-hidden="true" />}>
        <div className="mb-4 flex items-center justify-between gap-3">
          <div className="flex-1">
            <label id="https-label" className="text-sm font-medium text-foreground">{t("settings.network.httpsLabel")}</label>
            <p className="mt-1 text-xs text-muted-foreground">{t("settings.network.httpsHint")}</p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={https}
            aria-labelledby="https-label"
            onClick={onToggleHttps}
            disabled={networkBusy || !online}
            title={offlineTip}
            className={cn(
              "relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors min-h-[--control-min] min-w-[--control-min] md:min-h-6 md:min-w-11 disabled:cursor-not-allowed disabled:opacity-50",
              https ? "bg-success" : "bg-muted",
            )}
          >
            <span className={cn("pointer-events-none inline-block h-5 w-5 transform rounded-full bg-background shadow ring-0 transition", https ? "translate-x-5" : "translate-x-0")} />
          </button>
        </div>

        {httpsConfirm && !https && (
          <div className="mb-4 space-y-3 rounded-md border border-warning/30 bg-warning/5 p-3">
            <p className="text-xs text-muted-foreground">{t("settings.network.selfSignedNote")}</p>
            <div className="flex gap-2">
              <button type="button" onClick={() => setHttpsConfirm(false)} className={cn(secondaryBtnClass, "flex-1")}>{t("settings.cancel")}</button>
              <button type="button" onClick={onToggleHttps} disabled={networkBusy || !online} title={offlineTip} className={cn(primaryBtnClass, "flex-1")}>
                {t("settings.network.confirmHttps")}
              </button>
            </div>
          </div>
        )}

        <div className="mb-4 space-y-3">
          <div>
            <label htmlFor="cert-path" className="mb-1 block text-xs font-medium text-muted-foreground">{t("settings.network.certPath")}</label>
            <input id="cert-path" type="text" value={certPath} readOnly placeholder="data/certs/server.crt" className={cn(inputClass, "font-mono")} />
          </div>
          <div>
            <label htmlFor="key-path" className="mb-1 block text-xs font-medium text-muted-foreground">{t("settings.network.keyPath")}</label>
            <input id="key-path" type="text" value={keyPath} readOnly placeholder="data/certs/server.key" className={cn(inputClass, "font-mono")} />
          </div>
        </div>

        <button type="button" onClick={onGenCert} disabled={networkBusy || !online} title={offlineTip} className={secondaryBtnClass}>
          {t("settings.network.genCertButton")}
        </button>

        {/* Warning callout — the amber color rides the icon + hairline; the body
            text stays on the readable ink ramp (avoids washed-out amber-on-amber). */}
        <div className="mt-4 flex items-start gap-2 rounded-md border border-warning/30 bg-warning/5 p-3 text-xs text-muted-foreground">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden="true" />
          <span>{t("settings.network.selfSignedNote")}</span>
        </div>
      </FieldGroup>

      {/* Backup & Restore */}
      <FieldGroup title={t("settings.backup.title")} action={<Archive className="h-4 w-4 text-muted-foreground" aria-hidden="true" />}>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="space-y-2">
            <button type="button" onClick={onDownloadBackup} disabled={!online} title={offlineTip} className={cn(primaryBtnClass, "w-full")}>
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
              <button type="button" onClick={() => setRestoreConfirm(true)} className="w-full rounded-md border border-border px-3 py-2 text-sm font-medium text-danger hover:bg-danger/10 min-h-[--control-min] md:min-h-9">
                {t("settings.backup.uploadRestore")}
              </button>
            )}
            {restoreConfirm && (
              <div className="space-y-3 rounded-md border border-danger/30 bg-danger/5 p-3">
                <p className="text-xs text-muted-foreground">{t("settings.backup.confirmRestoreBody")}</p>
                <div className="flex gap-2">
                  <button type="button" onClick={() => setRestoreConfirm(false)} className={cn(secondaryBtnClass, "flex-1")}>{t("settings.cancel")}</button>
                  <button type="button" onClick={onRestore} className="flex-1 rounded-md bg-danger px-3 py-2 text-sm font-semibold text-white hover:bg-danger/90 min-h-[--control-min] md:min-h-9">
                    {t("settings.backup.confirmRestore")}
                  </button>
                </div>
              </div>
            )}
            <p className="text-xs text-muted-foreground">{t("settings.backup.restoreHint")}</p>
          </div>
        </div>
      </FieldGroup>
    </SectionPanel>
  );
}
