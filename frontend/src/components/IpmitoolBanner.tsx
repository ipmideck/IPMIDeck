import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { PackagePlus, PackageX, RotateCw } from "lucide-react";
import { get } from "@/api/client";
import { cn } from "@/lib/utils";
import { IpmitoolInstallDialog, type IpmitoolStatus } from "@/components/IpmitoolInstallDialog";

/**
 * Page-level banner shown while the backend cannot find ipmitool. Every server is reached
 * through it, so until it is installed nothing on screen can be live — this says so once,
 * at the top, instead of letting each action fail with an operating-system error. "Install"
 * opens what it takes on this host: the install itself when the backend may run it, otherwise
 * the command or the steps.
 *
 * Not dismissable: the condition breaks every feature, and hiding the notice would leave the
 * operator with failures and no explanation. It goes away on its own once "Check again" (or
 * the next page load) finds the program.
 */
export function IpmitoolBanner() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<IpmitoolStatus | null>(null);
  const [checking, setChecking] = useState(false);
  const [stillMissing, setStillMissing] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await get<{ ipmitool?: IpmitoolStatus }>("/api/config");
      setStatus(data.ipmitool ?? null);
      return data.ipmitool ?? null;
    } catch {
      // Backend not reachable: ConnectionBanner already says so.
      return null;
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const recheck = useCallback(async () => {
    setChecking(true);
    setStillMissing(false);
    const next = await load();
    setChecking(false);
    setStillMissing(next !== null && !next.available);
    return next;
  }, [load]);

  if (!status || status.available) return null;

  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-danger/40 bg-danger/10 px-4 py-2 text-xs"
    >
      <span className="flex items-center gap-2">
        <PackageX className="h-3.5 w-3.5 shrink-0 text-danger" aria-hidden="true" />
        <span className="font-semibold text-danger">{t("banner.ipmitoolMissing")}</span>
      </span>
      <span className="text-muted-foreground">{t("banner.ipmitoolMissingDetail")}</span>

      <span className="ml-auto flex items-center gap-2">
        {stillMissing && (
          <span className="text-muted-foreground" aria-live="polite">
            {t("banner.ipmitoolStillMissing")}
          </span>
        )}
        <button
          type="button"
          onClick={recheck}
          disabled={checking}
          className="flex items-center gap-1.5 rounded border border-border px-2 py-1 font-medium text-foreground transition-colors hover:bg-background/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
        >
          <RotateCw
            className={cn("h-3.5 w-3.5", checking && "animate-spin motion-reduce:animate-none")}
            aria-hidden="true"
          />
          {t("banner.ipmitoolRecheck")}
        </button>
        <button
          type="button"
          onClick={() => setDialogOpen(true)}
          className="flex items-center gap-1.5 rounded bg-primary px-2 py-1 font-semibold text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <PackagePlus className="h-3.5 w-3.5" aria-hidden="true" />
          {t("banner.ipmitoolInstall")}
        </button>
      </span>

      <IpmitoolInstallDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        status={status}
        onRecheck={recheck}
      />
    </div>
  );
}
