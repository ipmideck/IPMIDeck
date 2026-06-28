import { createContext, useContext } from "react";

/**
 * Shared Settings state, owned by the SettingsPage shell and consumed by the
 * URL-routed section panels.
 *
 * WHY a shell-owned context (D-13 medium caveat): under section routing each
 * panel mounts/unmounts as the URL changes. Any state held in a section's own
 * `useState` is lost on navigation. `certPath`/`keyPath` are NOT backend-seeded
 * (they're populated only by the in-session gen-cert action), so they MUST live
 * above the section switch or they vanish when the user leaves System and comes
 * back. The shell holds them (and the rest of the cross-section state) so the
 * panels stay thin and navigation-safe.
 */
export interface SettingsCtx {
  /** Backend reachable — every mutation disables + tooltips when false. */
  online: boolean;
  /** Tooltip shown on disabled mutation controls while offline. */
  offlineTip: string | undefined;

  // Network (System section) — lifted out of section-local state so the
  // generated cert/key paths survive navigating away from System and back.
  certPath: string;
  setCertPath: (v: string) => void;
  keyPath: string;
  setKeyPath: (v: string) => void;

  /** Live backend version (/api/health) for the About section. null -> "—". */
  appVersion: string | null;
}

export const SettingsContext = createContext<SettingsCtx | null>(null);

export function useSettings(): SettingsCtx {
  const ctx = useContext(SettingsContext);
  if (ctx == null) {
    throw new Error("useSettings must be used within the SettingsPage shell");
  }
  return ctx;
}
