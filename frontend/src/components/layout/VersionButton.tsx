import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { useUIOverlayStore } from "@/stores/ui-overlay-store";
import { useUpdateStore } from "@/stores/update-store";

interface VersionButtonProps {
  className?: string;
  /** Called after the dialog is opened — lets the mobile drawer close itself first. */
  onOpen?: () => void;
}

/**
 * The running version, as the control that opens the version history.
 *
 * One element doing three jobs: it says which build is running, it is the way into what
 * changed, and — only when there is genuinely a newer release — it carries the sole indication
 * that one exists. There is no banner, no toast and no modal that appears by itself; an
 * operator who is up to date sees a plain version string and nothing else.
 */
export function VersionButton({ className, onOpen }: VersionButtonProps) {
  const { t } = useTranslation();
  const setChangelogOpen = useUIOverlayStore((s) => s.setChangelogOpen);
  const state = useUpdateStore((s) => s.state);
  const loadState = useUpdateStore((s) => s.loadState);
  const watchState = useUpdateStore((s) => s.watchState);

  // Reads a cached row on the server; it never triggers a lookup of its own.
  useEffect(() => {
    if (state === null) void loadState();
  }, [state, loadState]);

  // Loading once is not enough on a page left open: the unattended check runs on the server and
  // its result would otherwise never reach this badge. Re-reads the same cached row when the tab
  // is shown again and, while the unattended check is on, once an hour.
  useEffect(() => watchState(), [watchState]);

  const version = state?.current_version ?? null;
  const updateAvailable = Boolean(state?.update_available);
  const isSecurity = Boolean(state?.is_security);

  const label = version
    ? t("updates.openChangelogFor", { version })
    : t("updates.openChangelog");

  return (
    <button
      type="button"
      onClick={() => {
        setChangelogOpen(true);
        onOpen?.();
      }}
      aria-label={label}
      aria-describedby={updateAvailable ? "sidebar-update-hint" : undefined}
      className={cn(
        "ml-1 inline-flex items-center gap-1 rounded px-1 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40",
        className,
      )}
    >
      <span className="font-mono">{version ? `v${version}` : "—"}</span>
      {updateAvailable && (
        <>
          {/* The dot is the quiet signal; the word next to it is what makes it readable
              without colour, and the hidden sentence is what makes it readable without sight. */}
          <span
            aria-hidden="true"
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              isSecurity ? "bg-danger" : "bg-primary",
            )}
          />
          <span className={cn("font-medium", isSecurity ? "text-danger" : "text-primary")}>
            {t("updates.new")}
          </span>
          <span id="sidebar-update-hint" className="sr-only">
            {isSecurity
              ? t("updates.securityUpdateAvailable", { version: state?.latest_version })
              : t("updates.updateAvailable", { version: state?.latest_version })}
          </span>
        </>
      )}
    </button>
  );
}
