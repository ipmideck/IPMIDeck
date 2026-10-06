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
 * Two jobs: it says which build is running, and it is the way into what changed. A newer
 * release is announced by the upgrade button beside it, not here, so an operator who is up to
 * date sees a plain version string and nothing else.
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
  // its result would otherwise never reach the upgrade button. Re-reads the same cached row when the tab
  // is shown again and, while the unattended check is on, once an hour.
  useEffect(() => watchState(), [watchState]);

  const version = state?.current_version ?? null;

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
      className={cn(
        "ml-1 inline-flex items-center gap-1 rounded px-1 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40",
        className,
      )}
    >
      <span className="font-mono">{version ? `v${version}` : "—"}</span>
    </button>
  );
}
