import { useTranslation } from "react-i18next";
import { ArrowUpCircle, ShieldAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import { useUIOverlayStore } from "@/stores/ui-overlay-store";
import { useUpdateStore } from "@/stores/update-store";

interface UpgradeButtonProps {
  className?: string;
  /** Called after the dialog is opened — lets the mobile drawer close itself first. */
  onOpen?: () => void;
}

/**
 * Beside the logo while a newer version is published and not installed: the standing way into
 * its release notes and its install. Absent otherwise, so an up-to-date sidebar is unchanged.
 * An icon only, so the name and version beside it keep their line; its label and tooltip name
 * the version, and a security release says so with its own glyph, not by colour alone.
 */
export function UpgradeButton({ className, onOpen }: UpgradeButtonProps) {
  const { t } = useTranslation();
  const setUpdateOpen = useUIOverlayStore((s) => s.setUpdateOpen);
  const state = useUpdateStore((s) => s.state);

  if (!state?.update_available || !state.latest_version) return null;
  const isSecurity = Boolean(state.is_security);

  return (
    <button
      type="button"
      onClick={() => {
        setUpdateOpen(true);
        onOpen?.();
      }}
      aria-label={
        isSecurity
          ? t("updateDialog.upgradeSecurityLabel", { version: state.latest_version })
          : t("updateDialog.upgradeLabel", { version: state.latest_version })
      }
      title={
        isSecurity
          ? t("updates.securityUpdateAvailable", { version: state.latest_version })
          : t("updates.updateAvailable", { version: state.latest_version })
      }
      className={cn(
        "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40",
        isSecurity
          ? "border-danger/40 bg-danger/10 text-danger hover:bg-danger/15"
          : "border-primary/40 bg-primary/10 text-primary hover:bg-primary/15",
        className,
      )}
    >
      {isSecurity ? (
        <ShieldAlert className="h-4 w-4" aria-hidden="true" />
      ) : (
        <ArrowUpCircle className="h-4 w-4" aria-hidden="true" />
      )}
    </button>
  );
}
