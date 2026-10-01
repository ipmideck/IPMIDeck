import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertCircle,
  CheckCircle2,
  ExternalLink,
  Heart,
  Code2,
  Globe,
  Loader2,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useUIOverlayStore } from "@/stores/ui-overlay-store";
import { useUpdateStore } from "@/stores/update-store";
import { useSettings } from "./SettingsContext";
import { SectionPanel, FieldGroup, secondaryBtnClass } from "./primitives";

interface AboutSectionProps {
  headingRef: React.Ref<HTMLHeadingElement>;
}

/** Localised install-method label, falling back to the raw value for anything unexpected. */
function useInstallLabel(method: string | undefined) {
  const { t } = useTranslation();
  if (!method) return null;
  const known: Record<string, string> = {
    docker: t("updates.methodDocker"),
    pip: t("updates.methodPip"),
    git: t("updates.methodGit"),
    unknown: t("updates.methodUnknown"),
  };
  return known[method] ?? method;
}

/**
 * About section — live version (/api/config), creator attribution (VERBATIM,
 * preserved from the monolith; no new/duplicated personal data), and sponsor.
 *
 * It also carries the update controls, because this is where an operator already comes to ask
 * "what am I running": the version, what changed in it, whether a newer one exists, and whether
 * the app is allowed to find out.
 */
export function AboutSection({ headingRef }: AboutSectionProps) {
  const { t } = useTranslation();
  const { appVersion, online, offlineTip } = useSettings();
  const setChangelogOpen = useUIOverlayStore((s) => s.setChangelogOpen);

  const state = useUpdateStore((s) => s.state);
  const loadState = useUpdateStore((s) => s.loadState);
  const checkNow = useUpdateStore((s) => s.checkNow);
  const setConsent = useUpdateStore((s) => s.setConsent);
  const checking = useUpdateStore((s) => s.checking);

  // The outcome of the last button press, distinct from the stored state: pressing Check and
  // learning "you are already up to date" is an answer, and it has to be visible even though
  // nothing about the state changed.
  const [result, setResult] = useState<"upToDate" | "available" | "failed" | null>(null);
  const [consentError, setConsentError] = useState(false);

  useEffect(() => {
    if (state === null) void loadState();
  }, [state, loadState]);

  const installLabel = useInstallLabel(state?.install_method);
  const suppressed = state !== null && !state.enabled;
  const consent = Boolean(state?.consent);
  const version = appVersion ?? state?.current_version ?? null;

  const lastChecked = state?.checked_at
    ? new Date(state.checked_at).toLocaleString()
    : null;

  async function handleCheck() {
    setResult(null);
    const next = await checkNow();
    if (next === null || next.error) setResult("failed");
    else setResult(next.update_available ? "available" : "upToDate");
  }

  async function handleConsent(next: boolean) {
    setConsentError(false);
    try {
      await setConsent(next);
    } catch {
      setConsentError(true);
    }
  }

  return (
    <SectionPanel
      ref={headingRef}
      headingId="settings-panel-heading"
      title={t("settings.about.title")}
      description={t("settings.sections.aboutDescription")}
    >
      <FieldGroup title={t("settings.about.title")}>
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm text-muted-foreground">{t("settings.version")}</span>
            {/* The version opens the same history the sidebar opens — one place to read it. */}
            <button
              type="button"
              onClick={() => setChangelogOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 font-mono text-sm min-h-[--control-min] md:min-h-8 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
            >
              {version ?? "—"}
              <span className="font-sans text-xs text-muted-foreground underline underline-offset-2">
                {t("updates.releaseNotes")}
              </span>
            </button>
          </div>
          <div className="border-t border-border/60" />
          <div className="flex items-start gap-3 pt-1">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-muted text-sm font-semibold">LT</div>
            <div>
              <p className="text-sm font-medium">Luigi Tanzillo</p>
              <p className="text-xs text-muted-foreground">{t("settings.creatorRole")}</p>
              <div className="mt-1.5 flex flex-wrap items-center gap-2">
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
      </FieldGroup>

      <FieldGroup
        title={t("updates.settingsTitle")}
        description={t("updates.settingsDescription")}
      >
        {/* When the configuration forbids it, the controls are inert AND the reason is named.
            An operator must never be left clicking something that silently does nothing. */}
        {suppressed && (
          <p
            role="status"
            className="mb-4 flex items-start gap-2 rounded-lg border border-border bg-muted/50 px-3 py-2 text-xs text-muted-foreground"
          >
            <AlertCircle className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span>{t("updates.suppressedByConfig")}</span>
          </p>
        )}

        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0 flex-1">
            <label id="updates-consent-label" className="text-sm font-medium text-foreground">
              {t("updates.consentLabel")}
            </label>
            <p className="mt-1 text-xs text-muted-foreground">{t("updates.consentHint")}</p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={consent}
            aria-labelledby="updates-consent-label"
            disabled={suppressed || !online}
            title={!online ? offlineTip : undefined}
            onClick={() => void handleConsent(!consent)}
            className={cn(
              "relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors min-h-[--control-min] min-w-[--control-min] md:min-h-6 md:min-w-11 disabled:cursor-not-allowed disabled:opacity-50",
              consent ? "bg-success" : "bg-muted",
            )}
          >
            <span
              className={cn(
                "pointer-events-none inline-block h-5 w-5 transform rounded-full bg-background shadow ring-0 transition",
                consent ? "translate-x-5" : "translate-x-0",
              )}
            />
          </button>
        </div>

        {consentError && (
          <p role="alert" className="mt-2 flex items-center gap-1.5 text-xs text-danger">
            <AlertCircle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            {t("updates.consentFailed")}
          </p>
        )}

        <div className="mt-5 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => void handleCheck()}
            disabled={suppressed || checking || !online}
            title={!online ? offlineTip : undefined}
            className={cn(secondaryBtnClass, "inline-flex items-center gap-2")}
          >
            {checking ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
            )}
            {checking ? t("updates.checking") : t("updates.checkNow")}
          </button>

          {lastChecked && (
            <span className="text-xs text-muted-foreground">
              {t("updates.lastChecked", { when: lastChecked })}
            </span>
          )}
        </div>

        {/* Every outcome is announced, and none of them relies on colour alone. */}
        <div className="mt-3 min-h-[1.25rem]">
          {result === "upToDate" && (
            <p role="status" className="flex items-center gap-1.5 text-xs text-success">
              <CheckCircle2 className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              {t("updates.upToDate", { version: version ?? "" })}
            </p>
          )}
          {result === "available" && (
            <p
              role="status"
              className={cn(
                "flex flex-wrap items-center gap-1.5 text-xs",
                state?.is_security ? "text-danger" : "text-foreground",
              )}
            >
              {state?.is_security ? (
                <ShieldAlert className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              ) : (
                <CheckCircle2 className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              )}
              {state?.is_security
                ? t("updates.securityUpdateAvailable", { version: state?.latest_version })
                : t("updates.updateAvailable", { version: state?.latest_version })}
              <a
                href={state?.release_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 underline underline-offset-2 hover:no-underline"
              >
                {t("updates.viewRelease")}
                <ExternalLink className="h-3 w-3" aria-hidden="true" />
              </a>
            </p>
          )}
          {result === "failed" && (
            <p role="alert" className="flex items-center gap-1.5 text-xs text-danger">
              <AlertCircle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              {t("updates.checkFailed")}
            </p>
          )}
        </div>

        {installLabel && (
          <p className="mt-4 text-xs text-muted-foreground">
            {t("updates.installMethod", { method: installLabel })}
          </p>
        )}
      </FieldGroup>
    </SectionPanel>
  );
}
