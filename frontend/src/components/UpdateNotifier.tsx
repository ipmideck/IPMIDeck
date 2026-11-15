import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useUIOverlayStore } from "@/stores/ui-overlay-store";
import { useUpdateStore } from "@/stores/update-store";

/** The newest version this browser has already been told about. */
export const UPDATE_TOAST_KEY = "ipmideck.updateToastFor";

function alreadyTold(version: string): boolean {
  try {
    if (localStorage.getItem(UPDATE_TOAST_KEY) === version) return true;
    localStorage.setItem(UPDATE_TOAST_KEY, version);
  } catch {
    // No storage (a private window, say): told once per page load instead.
  }
  return false;
}

/**
 * Says once, per version and per browser, that a newer version has been found, with the way
 * into its notes and its install. It only reads the state the update check left behind; it
 * never asks for a check. After that the upgrade button beside the logo carries the news.
 */
export function UpdateNotifier() {
  const { t } = useTranslation();
  const state = useUpdateStore((s) => s.state);
  const setUpdateOpen = useUIOverlayStore((s) => s.setUpdateOpen);

  const version = state?.update_available ? state.latest_version : null;
  const isSecurity = Boolean(state?.is_security);

  useEffect(() => {
    if (!version || alreadyTold(version)) return;
    const show = isSecurity ? toast.warning : toast;
    show(
      isSecurity
        ? t("updates.securityUpdateAvailable", { version })
        : t("updates.updateAvailable", { version }),
      {
        id: `update-${version}`,
        description: t("updateDialog.toastDetail"),
        duration: 15000,
        action: {
          label: t("updateDialog.toastAction"),
          onClick: () => setUpdateOpen(true),
        },
      },
    );
  }, [version, isSecurity, t, setUpdateOpen]);

  return null;
}
