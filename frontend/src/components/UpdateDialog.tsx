import { useEffect } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useTranslation } from "react-i18next";
import {
  BookOpen,
  Check,
  CircleCheck,
  Download,
  ExternalLink,
  Loader2,
  ShieldAlert,
  Sparkles,
  TriangleAlert,
  X,
} from "lucide-react";
import { CommandLine } from "@/components/CommandLine";
import { ReleaseNotesBody } from "@/components/ReleaseNotes";
import { SUPPORTED_LNGS } from "@/i18n/languages";
import { cn } from "@/lib/utils";
import { useUIOverlayStore } from "@/stores/ui-overlay-store";
import {
  isActive,
  useUpdateInstallStore,
  type InstallSnapshot,
} from "@/stores/update-install-store";
import { useUpdateStore, type UpgradePlan } from "@/stores/update-store";

/** The docs site keeps a page per UI language, under the same codes; anything else reads English. */
export function updateGuideUrl(language: string | undefined): string {
  const code = (SUPPORTED_LNGS as readonly string[]).includes(language ?? "") ? language : "en";
  return `https://docs.ipmideck.com/${code}/update-from-web-ui`;
}

/** The reasons the server gives for not installing, each with its own explanation. */
const REASONS = new Set([
  "docker",
  "git",
  "unknown",
  "editable",
  "system_python",
  "tool_missing",
  "pip_missing",
  "manual_only",
  "no_update",
  "demo",
  "needs_login",
  "busy",
  "backup_failed",
  "watchtower_unauthorized",
  "watchtower_refused",
  "watchtower_unreachable",
  "timeout",
  "failed",
  "not_installed",
  "not_possible",
]);

/** The phases that come after the backup, when the server has said where it put it. */
const SHOWS_BACKUP = new Set<InstallSnapshot["phase"]>([
  "installing",
  "restarting",
  "restart_required",
  "failed",
]);

function reasonOf(code: string | null | undefined): string {
  const reason = (code ?? "").replace(/^update_/, "");
  return REASONS.has(reason) ? reason : "failed";
}

type RestartMode = "automatic" | "manual" | "container";

function restartOf(snapshot: InstallSnapshot, plan: UpgradePlan | null): RestartMode {
  return snapshot.restart ?? plan?.restart ?? "automatic";
}

/** Which of the three steps is under way: back up, install, come back. 3 means all done. */
function stepOf(snapshot: InstallSnapshot, restart: RestartMode): number {
  switch (snapshot.phase) {
    case "starting":
    case "backing_up":
      return 0;
    case "installing":
      return 1;
    // On Windows the install itself runs after IPMIDeck has stopped.
    case "restarting":
      return restart === "manual" ? 1 : 2;
    default:
      return 3;
  }
}

function Steps({
  current,
  labels,
}: {
  current: number;
  labels: [string, string, string];
}) {
  return (
    <ol className="space-y-2">
      {labels.map((label, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <li
            key={i}
            aria-current={active ? "step" : undefined}
            className={cn(
              "flex items-center gap-2.5 text-[13px]",
              done || active ? "text-foreground" : "text-muted-foreground",
            )}
          >
            <span
              aria-hidden="true"
              className={cn(
                "flex h-5 w-5 shrink-0 items-center justify-center rounded-full border",
                done && "border-success/50 bg-success/15 text-success",
                active && "border-primary/50 bg-primary/10 text-primary",
                !done && !active && "border-border text-muted-foreground",
              )}
            >
              {done ? (
                <Check className="h-3 w-3" />
              ) : active ? (
                <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" />
              ) : (
                <span className="font-mono text-[10px]">{i + 1}</span>
              )}
            </span>
            <span className={cn(active && "font-medium")}>{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

/**
 * The newer version: what changed in it, and installing it the way this copy was installed.
 *
 * The server decides whether it can install by itself (a pip, pipx or uv install it is allowed
 * to touch, or a Docker install with Watchtower beside it); otherwise this shows why not and the
 * command to run. While an install runs, the dialog follows it to the end: the page reloads by
 * itself once the new version answers.
 */
export function UpdateDialog() {
  const { t, i18n } = useTranslation();
  const open = useUIOverlayStore((s) => s.updateOpen);
  const setOpen = useUIOverlayStore((s) => s.setUpdateOpen);

  const state = useUpdateStore((s) => s.state);
  const releasesUrl = useUpdateStore((s) => s.releasesUrl);

  const snapshot = useUpdateInstallStore((s) => s.snapshot);
  const slow = useUpdateInstallStore((s) => s.slow);
  const start = useUpdateInstallStore((s) => s.start);
  const resume = useUpdateInstallStore((s) => s.resume);
  const reset = useUpdateInstallStore((s) => s.reset);

  // An update started from another tab, or before this page was reloaded, is followed too.
  useEffect(() => {
    if (open) void resume();
  }, [open, resume]);

  const phase = snapshot.phase;
  const plan = state?.upgrade ?? null;
  const restart = restartOf(snapshot, plan);
  const running = isActive(phase) || phase === "back";
  // Once IPMIDeck has stopped for a manual start, nothing more happens here until the operator
  // starts it again, so the dialog may be put away. Until then it stays with the install.
  const locked = running && !(phase === "restarting" && restart === "manual");

  const target = snapshot.target ?? state?.latest_version ?? null;
  const current = state?.current_version ?? null;
  const isSecurity = Boolean(state?.is_security);
  const notes = state?.notes ?? null;
  const releaseUrl = state?.release_url || releasesUrl;
  const container = plan?.mechanism === "watchtower" || restart === "container";

  const onOpenChange = (next: boolean) => {
    if (!next && locked) return;
    setOpen(next);
    if (!next && phase === "failed") reset();
  };

  const stepLabels: [string, string, string] = [
    t("updateDialog.steps.backup"),
    container
      ? t("updateDialog.steps.installContainer")
      : t("updateDialog.steps.install", { version: target ?? "" }),
    restart === "manual"
      ? t("updateDialog.steps.restartManual")
      : restart === "container"
        ? t("updateDialog.steps.restartContainer")
        : t("updateDialog.steps.restart"),
  ];

  const showCommand =
    plan?.command && plan.reason !== "system_python" ? plan.command : null;

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60" />
        <Dialog.Content
          onEscapeKeyDown={(e) => locked && e.preventDefault()}
          onPointerDownOutside={(e) => locked && e.preventDefault()}
          className={cn(
            "fixed z-50 flex flex-col overflow-hidden border border-border bg-popover text-popover-foreground shadow-2xl",
            // Below sm the whole screen: release notes are long and a phone has no room to spare.
            "inset-0 rounded-none",
            "sm:inset-auto sm:left-1/2 sm:top-1/2 sm:max-h-[88vh] sm:w-[min(48rem,calc(100vw-2rem))] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-xl",
          )}
        >
          <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4 sm:px-6">
            <div className="flex min-w-0 items-start gap-3">
              <span
                aria-hidden="true"
                className={cn(
                  "mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
                  isSecurity ? "bg-danger/10 text-danger" : "bg-primary/10 text-primary",
                )}
              >
                {isSecurity ? <ShieldAlert className="h-4.5 w-4.5" /> : <Sparkles className="h-4.5 w-4.5" />}
              </span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                  <Dialog.Title className="text-lg font-semibold [text-wrap:balance]">
                    {t("updateDialog.title", { version: target ?? "" })}
                  </Dialog.Title>
                  {isSecurity && (
                    <span className="inline-flex items-center gap-1 rounded-full border border-danger/40 bg-danger/10 px-2 py-0.5 text-[11px] font-medium text-danger">
                      <ShieldAlert className="h-3 w-3" aria-hidden="true" />
                      {t("updates.securityRelease")}
                    </span>
                  )}
                </div>
                <Dialog.Description className="mt-0.5 text-xs text-muted-foreground">
                  {current
                    ? t("updateDialog.running", { version: current })
                    : t("updateDialog.subtitle")}
                </Dialog.Description>
              </div>
            </div>
            <Dialog.Close
              disabled={locked}
              className="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
              aria-label={t("common.close")}
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </Dialog.Close>
          </div>

          {isSecurity && (
            <p className="flex items-start gap-2 border-b border-danger/30 bg-danger/10 px-5 py-2.5 text-sm text-danger sm:px-6">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              {t("updateDialog.securityNote")}
            </p>
          )}

          {/* tabIndex: long notes must scroll from the keyboard too. */}
          <div
            className="min-h-0 flex-1 overflow-y-auto px-5 py-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 sm:px-6"
            tabIndex={0}
            role="region"
            aria-label={t("updates.releaseNotes")}
          >
            {notes ? (
              <ReleaseNotesBody body={notes} />
            ) : (
              <p className="text-sm text-muted-foreground">
                {t("updateDialog.notesMissing")}{" "}
                <a
                  href={releaseUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-foreground underline underline-offset-2 hover:no-underline"
                >
                  {t("updates.viewRelease")}
                  <ExternalLink className="h-3 w-3" aria-hidden="true" />
                </a>
              </p>
            )}
          </div>

          <section
            aria-label={t("updateDialog.installHeading")}
            className="space-y-3 border-t border-border bg-muted/30 px-5 py-4 text-[13px] leading-relaxed sm:px-6"
          >
            {phase === "idle" && plan?.automatic && (
              <p className="max-w-[70ch] text-muted-foreground">
                {t("updateDialog.backupFirst")}{" "}
                {t(`updateDialog.after.${restart}`, {
                  version: target ?? "",
                  mechanism: plan.mechanism ?? "pip",
                })}
              </p>
            )}

            {phase === "idle" && plan && !plan.automatic && (
              <div>
                <p className="flex max-w-[70ch] items-start gap-2 text-foreground">
                  <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden="true" />
                  <span>{t(`updateDialog.reason.${reasonOf(plan.reason)}`)}</span>
                </p>
                {showCommand && (
                  <>
                    <p className="mt-3 text-muted-foreground">{t("updateDialog.runYourself")}</p>
                    <CommandLine command={showCommand} />
                  </>
                )}
              </div>
            )}

            {running && (
              <div className="space-y-3">
                <Steps current={stepOf(snapshot, restart)} labels={stepLabels} />
                <p role="status" className="max-w-[70ch] text-muted-foreground">
                  {phase === "back"
                    ? t("updateDialog.back", { version: target ?? "" })
                    : phase === "restarting" && restart === "manual"
                      ? t("updateDialog.stopped")
                      : phase === "restarting"
                        ? t("updateDialog.waiting", { version: target ?? "" })
                        : t("updateDialog.keepRunning")}
                  {slow && phase === "restarting" && restart !== "manual" && (
                    <span className="mt-1 block text-warning">{t("updateDialog.slow")}</span>
                  )}
                </p>
              </div>
            )}

            {phase === "restart_required" && (
              <p role="status" className="flex items-start gap-2 text-foreground">
                <CircleCheck className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
                {t("updateDialog.restartRequired", { version: target ?? "" })}
              </p>
            )}

            {phase === "failed" && (
              <>
                <div
                  role="alert"
                  className="rounded-lg border border-danger/30 bg-danger/10 px-3 py-2.5 text-danger"
                >
                  <p className="font-medium">{t("updateDialog.failed")}</p>
                  <p className="mt-1 text-foreground/90">
                    {t(`updateDialog.reason.${reasonOf(snapshot.error_code)}`)}
                  </p>
                </div>
                {snapshot.output && (
                  <details className="rounded-md border border-border bg-background/40">
                    <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-muted-foreground">
                      {t("updateDialog.output")}
                    </summary>
                    <pre className="max-h-48 overflow-auto border-t border-border px-3 py-2 font-mono text-[11px] leading-snug text-foreground">
                      {snapshot.output}
                    </pre>
                  </details>
                )}
                {showCommand && (
                  <div>
                    <p className="text-muted-foreground">{t("updateDialog.runYourself")}</p>
                    <CommandLine command={showCommand} />
                  </div>
                )}
              </>
            )}

            {snapshot.backup && SHOWS_BACKUP.has(phase) && (
              <div>
                <p className="text-muted-foreground">{t("updateDialog.backupLocation")}</p>
                <code className="mt-1 block select-all break-all font-mono text-xs text-foreground">
                  {snapshot.backup}
                </code>
                <p className="mt-1 max-w-[70ch] text-xs text-muted-foreground">
                  {t("updateDialog.backupPrivate")}
                </p>
              </div>
            )}

            {/* How each install method behaves, and how to set up Watchtower for Docker. */}
            {((phase === "idle" && plan) || phase === "failed") && (
              <a
                href={updateGuideUrl(i18n.resolvedLanguage)}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
              >
                <BookOpen className="h-3.5 w-3.5" aria-hidden="true" />
                {t("updateDialog.guide")}
                <ExternalLink className="h-3 w-3" aria-hidden="true" />
              </a>
            )}
          </section>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-3 sm:px-6">
            <a
              href={releaseUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
            >
              {t("updates.viewRelease")}
              <ExternalLink className="h-3 w-3" aria-hidden="true" />
            </a>
            <div className="ml-auto flex items-center gap-2">
              {!locked && (
                <Dialog.Close className="min-h-[--control-min] rounded-md border border-border px-3 py-1.5 text-sm font-medium hover:bg-muted md:min-h-8">
                  {phase === "idle" && plan?.automatic ? t("updateDialog.later") : t("common.close")}
                </Dialog.Close>
              )}
              {plan?.automatic && (phase === "idle" || phase === "failed" || locked) && (
                <button
                  type="button"
                  onClick={() => void start()}
                  disabled={locked}
                  className="inline-flex min-h-[--control-min] items-center gap-1.5 rounded-md bg-primary px-3.5 py-1.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-70 md:min-h-8"
                >
                  {locked ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                  ) : (
                    <Download className="h-3.5 w-3.5" aria-hidden="true" />
                  )}
                  {locked
                    ? t("updateDialog.installing")
                    : phase === "failed"
                      ? t("updateDialog.retry")
                      : t("updateDialog.install")}
                </button>
              )}
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
