import { useEffect, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useTranslation } from "react-i18next";
import { CircleCheck, Loader2, PackagePlus, TriangleAlert, X } from "lucide-react";
import { post } from "@/api/client";
import { CommandLine } from "@/components/CommandLine";
import { cn } from "@/lib/utils";

export interface IpmitoolStatus {
  available: boolean;
  install_command: string | null;
  platform: "windows" | "macos" | "linux" | "other";
  install?: { automatic: boolean; reason: string | null };
  os_label?: string;
  search_dirs?: string[];
}

interface InstallResult {
  success: boolean;
  error_code?: string;
  output?: string;
}

type Phase = "idle" | "installing" | "done" | "failed";

/** The reasons the backend gives for not installing, each with its own explanation. */
const REASONS = new Set([
  "disabled",
  "no_privileges",
  "brew_missing",
  "docker",
  "unsupported",
  "needs_login",
  "demo",
  "busy",
  "timeout",
  "not_found",
  "failed",
]);

function reasonOf(code: string | null | undefined): string {
  const reason = (code ?? "").replace(/^ipmitool_install_/, "");
  return REASONS.has(reason) ? reason : "failed";
}

interface IpmitoolInstallDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  status: IpmitoolStatus;
  /** Re-read the status; resolves to the fresh one. */
  onRecheck: () => Promise<IpmitoolStatus | null>;
}

/**
 * What it takes to install ipmitool on the machine running IPMIDeck, and doing it when the
 * backend can. The backend decides: it installs only when allowed in config.yaml and already
 * privileged, so this dialog never asks for a password — it explains why it cannot, and shows
 * the command to run instead.
 */
export function IpmitoolInstallDialog({
  open,
  onOpenChange,
  status,
  onRecheck,
}: IpmitoolInstallDialogProps) {
  const { t } = useTranslation();
  const [phase, setPhase] = useState<Phase>("idle");
  const [result, setResult] = useState<InstallResult | null>(null);

  useEffect(() => {
    if (open) {
      setPhase("idle");
      setResult(null);
    }
  }, [open]);

  const automatic = Boolean(status.install?.automatic);
  const reason = status.install?.reason ?? null;
  const command = status.install_command;
  const windows = status.platform === "windows";

  const install = async () => {
    setPhase("installing");
    let answer: InstallResult;
    try {
      answer = await post<InstallResult>("/api/system/ipmitool/install");
    } catch {
      answer = { success: false, error_code: "ipmitool_install_failed" };
    }
    setResult(answer);
    setPhase(answer.success ? "done" : "failed");
    if (answer.success) void onRecheck();
  };

  const failedReason = phase === "failed" ? reasonOf(result?.error_code) : null;

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        // An install in progress cannot be stopped from here, so the dialog stays with it.
        if (phase !== "installing") onOpenChange(next);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/50" />
        <Dialog.Content className="fixed inset-x-0 bottom-0 top-0 z-50 flex flex-col overflow-hidden border border-border bg-popover text-popover-foreground shadow-2xl sm:inset-auto sm:left-1/2 sm:top-1/2 sm:max-h-[85vh] sm:w-[min(34rem,calc(100vw-2rem))] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-xl">
          <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
            <div className="min-w-0">
              <Dialog.Title className="flex items-center gap-2 text-base font-semibold">
                <PackagePlus className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                {t("ipmitoolInstall.title")}
              </Dialog.Title>
              <Dialog.Description className="mt-0.5 text-xs text-muted-foreground">
                {t("ipmitoolInstall.detected", { os: status.os_label ?? status.platform })}
              </Dialog.Description>
            </div>
            <Dialog.Close
              disabled={phase === "installing"}
              className="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
              aria-label={t("common.close")}
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </Dialog.Close>
          </div>

          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4 text-[13px] leading-relaxed">
            {phase === "done" && (
              <p role="status" className="flex items-start gap-2 text-foreground">
                <CircleCheck className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
                {t("ipmitoolInstall.success")}
              </p>
            )}

            {phase === "failed" && failedReason && (
              <div
                role="alert"
                className="rounded-lg border border-danger/30 bg-danger/10 px-3 py-2.5 text-danger"
              >
                <p className="font-medium">{t("ipmitoolInstall.failed")}</p>
                <p className="mt-1 text-foreground/90">{t(`ipmitoolInstall.reason.${failedReason}`)}</p>
              </div>
            )}

            {phase !== "done" && windows && (
              <div>
                <p className="text-muted-foreground">{t("ipmitoolInstall.windows.intro")}</p>
                <ol className="mt-2 list-decimal space-y-1.5 pl-5 text-foreground">
                  <li>{t("ipmitoolInstall.windows.step1")}</li>
                  <li>{t("ipmitoolInstall.windows.step2")}</li>
                  <li>{t("ipmitoolInstall.windows.step3")}</li>
                </ol>
                {status.search_dirs && status.search_dirs.length > 0 && (
                  <div className="mt-3">
                    <p className="text-xs text-muted-foreground">{t("ipmitoolInstall.windows.searched")}</p>
                    <ul className="mt-1 space-y-0.5">
                      {status.search_dirs.map((dir) => (
                        <li key={dir} className="break-all font-mono text-xs text-foreground">
                          {dir}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {phase !== "done" && !windows && automatic && phase !== "failed" && command && (
              <div>
                <p className="text-muted-foreground">{t("ipmitoolInstall.whatRuns")}</p>
                <CommandLine command={command} />
              </div>
            )}

            {phase !== "done" && !windows && (!automatic || phase === "failed") && (
              <div>
                {!automatic && reason && reason !== "windows" && (
                  <p className="flex items-start gap-2 text-foreground">
                    <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden="true" />
                    <span>{t(`ipmitoolInstall.reason.${reasonOf(reason)}`)}</span>
                  </p>
                )}
                {command && reason !== "docker" && (
                  <>
                    <p className="mt-3 text-muted-foreground">{t("ipmitoolInstall.runYourself")}</p>
                    <CommandLine command={command} />
                  </>
                )}
              </div>
            )}

            {phase === "failed" && result?.output && (
              <details className="rounded-md border border-border">
                <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-muted-foreground">
                  {t("ipmitoolInstall.output")}
                </summary>
                <pre className="max-h-48 overflow-auto border-t border-border px-3 py-2 font-mono text-[11px] leading-snug text-foreground">
                  {result.output}
                </pre>
              </details>
            )}
          </div>

          <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
            {phase === "done" ? (
              <Dialog.Close className="rounded-md border border-border px-3 py-1.5 text-sm font-medium hover:bg-muted">
                {t("common.close")}
              </Dialog.Close>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => void onRecheck()}
                  disabled={phase === "installing"}
                  className="rounded-md border border-border px-3 py-1.5 text-sm font-medium hover:bg-muted disabled:opacity-50"
                >
                  {t("banner.ipmitoolRecheck")}
                </button>
                {automatic && !windows && (
                  <button
                    type="button"
                    onClick={install}
                    disabled={phase === "installing"}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-70",
                    )}
                  >
                    {/* The spinner takes the icon's place, so the button keeps its width. */}
                    {phase === "installing" ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                    ) : (
                      <PackagePlus className="h-3.5 w-3.5" aria-hidden="true" />
                    )}
                    {phase === "installing"
                      ? t("ipmitoolInstall.installing")
                      : phase === "failed"
                        ? t("ipmitoolInstall.retry")
                        : t("ipmitoolInstall.installNow")}
                  </button>
                )}
              </>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
