/**
 * Recover from a page that outlived its build.
 *
 * Every page is loaded on demand from a bundle whose name carries a hash of its contents. After
 * an upgrade those names change and the old bundles are gone, so a tab opened before the upgrade
 * fails with "Failed to fetch dynamically imported module" on the next navigation. Reloading
 * fetches the current page, which names the current bundles.
 *
 * At most one reload per minute: if the bundle is missing for some other reason, a second
 * failure right after the reload is shown as the error it is instead of looping.
 */

const STORAGE_KEY = "ipmideck.staleBundleReloadAt";
const MIN_INTERVAL_MS = 60_000;

interface ReloadDeps {
  storage: Pick<Storage, "getItem" | "setItem">;
  reload: () => void;
  now: () => number;
}

/** Reload unless one was already attempted within the last minute; true when it reloads. */
export function reloadForStaleBundle({ storage, reload, now }: ReloadDeps): boolean {
  let last = 0;
  try {
    last = Number(storage.getItem(STORAGE_KEY)) || 0;
  } catch {
    // Unreadable storage: the write below decides.
  }
  if (now() - last < MIN_INTERVAL_MS) return false;
  try {
    storage.setItem(STORAGE_KEY, String(now()));
  } catch {
    // A reload that cannot be remembered cannot be limited, so it is not attempted.
    return false;
  }
  reload();
  return true;
}

/** Listen for Vite's signal that an on-demand bundle could not be loaded. */
export function installStaleBundleReload(win: Window = window): void {
  win.addEventListener("vite:preloadError", (event) => {
    const reloading = reloadForStaleBundle({
      storage: win.sessionStorage,
      reload: () => win.location.reload(),
      now: () => Date.now(),
    });
    // Suppress the error only when a reload is on its way; otherwise let the boundary show it.
    if (reloading) event.preventDefault();
  });
}
