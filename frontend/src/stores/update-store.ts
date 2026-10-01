import { create } from "zustand";
import { get as apiGet, post, put } from "@/api/client";

export interface ChangelogEntry {
  version: string;
  date: string | null;
  is_security: boolean;
  is_unreleased: boolean;
  body: string;
}

export interface UpdateState {
  /** The version switch in the configuration. False means the app may never look. */
  enabled: boolean;
  /** The operator's own answer — governs the unattended check only. */
  consent: boolean;
  current_version: string | null;
  latest_version: string | null;
  update_available: boolean;
  is_security: boolean;
  release_url: string;
  install_method: string;
  checked_at: string | null;
  /** A machine-readable reason, never an exception string. */
  error: string | null;
}

interface UpdateStore {
  state: UpdateState | null;
  stateLoading: boolean;

  entries: ChangelogEntry[];
  changelogUrl: string;
  releasesUrl: string;
  /** null = not loaded yet; "" = loaded and empty is a legitimate outcome. */
  changelogLoaded: boolean;
  changelogLoading: boolean;
  changelogError: boolean;

  checking: boolean;

  loadState: () => Promise<void>;
  loadChangelog: () => Promise<void>;
  checkNow: () => Promise<UpdateState | null>;
  setConsent: (enabled: boolean) => Promise<void>;
  /**
   * Keep the cached state current while the page stays open. Returns the function that stops
   * it. Every caller shares one listener and one timer, so mounting it twice reads no more often.
   */
  watchState: () => () => void;
}

const DEFAULT_RELEASES = "https://github.com/ipmideck/IPMIDeck/releases";

/**
 * How often an open page re-reads the cached result while the unattended check is on. The
 * server checks once a day; this is only so a page left open for days learns what it found.
 */
export const STATE_REFRESH_MS = 60 * 60 * 1000;

/**
 * How long after the unattended check is switched on before the page re-reads the state.
 * Switching it on starts the first check at once on the server, and that check may make two
 * lookups of up to six seconds each, so this waits long enough for both to have finished.
 */
export const FIRST_CHECK_SETTLE_MS = 15 * 1000;

// Shared by every caller of watchState: one visibility listener and one interval, however many
// version buttons are mounted (the sidebar's and the mobile drawer's can be at the same time).
let watchers = 0;
let refreshTimer: ReturnType<typeof setInterval> | null = null;
let onVisible: (() => void) | null = null;
// The one-off read after consent is given. Kept apart from the watchers because it belongs to
// the answer, not to whichever component happens to be mounted when it fires.
let settleTimer: ReturnType<typeof setTimeout> | null = null;

/**
 * Update state and the packaged version history.
 *
 * The changelog is fetched once and kept: it is a file that shipped with the build, so it cannot
 * change while the page is open, and re-fetching it on every dialog open would make opening the
 * history feel slower than it is.
 *
 * Nothing here checks for a newer version on its own. `checkNow` is only ever called from a
 * button the operator pressed. The timers and the visibility listener below only ever re-read
 * the result the server already has; none of them asks for a check, because the check route
 * needs no consent and must stay something a person did.
 */
export const useUpdateStore = create<UpdateStore>((set, get) => ({
  state: null,
  stateLoading: false,
  entries: [],
  changelogUrl: "",
  releasesUrl: DEFAULT_RELEASES,
  changelogLoaded: false,
  changelogLoading: false,
  changelogError: false,
  checking: false,

  loadState: async () => {
    set({ stateLoading: true });
    try {
      const body = await apiGet<UpdateState & { success: boolean }>("/api/updates/state");
      set({ state: body, stateLoading: false });
    } catch {
      // The banner and the badge simply stay absent; there is nothing useful to say to the
      // operator about a state read that failed.
      set({ stateLoading: false });
    }
  },

  loadChangelog: async () => {
    if (get().changelogLoading) return;
    set({ changelogLoading: true, changelogError: false });
    try {
      const body = await apiGet<{
        entries: ChangelogEntry[];
        changelog_url: string;
        releases_url: string;
      }>("/api/updates/changelog");
      set({
        entries: body.entries ?? [],
        changelogUrl: body.changelog_url,
        releasesUrl: body.releases_url || DEFAULT_RELEASES,
        changelogLoaded: true,
        changelogLoading: false,
      });
    } catch {
      set({ changelogLoading: false, changelogError: true, changelogLoaded: true });
    }
  },

  checkNow: async () => {
    set({ checking: true });
    try {
      const body = await post<UpdateState & { success: boolean }>("/api/updates/check");
      const previous = get().state;
      const merged = { ...body, enabled: previous?.enabled ?? true, consent: previous?.consent ?? false };
      set({ state: merged, checking: false });
      return merged;
    } catch {
      set({ checking: false });
      return null;
    }
  },

  setConsent: async (enabled: boolean) => {
    await put("/api/updates/consent", { enabled });
    const previous = get().state;
    if (previous) set({ state: { ...previous, consent: enabled } });
    if (settleTimer !== null) {
      clearTimeout(settleTimer);
      settleTimer = null;
    }
    if (enabled) {
      // The first check has just started on the server. Without this read its result would
      // only appear on the next hourly tick, which reads as "nothing happened".
      settleTimer = setTimeout(() => {
        settleTimer = null;
        void get().loadState();
      }, FIRST_CHECK_SETTLE_MS);
    }
  },

  watchState: () => {
    watchers += 1;
    if (watchers === 1) {
      // Coming back to the tab is when a stale badge would be noticed, and it also picks up a
      // check made from elsewhere (another browser, or the console key) while consent is off.
      onVisible = () => {
        if (document.visibilityState === "visible" && !get().stateLoading) {
          void get().loadState();
        }
      };
      document.addEventListener("visibilitychange", onVisible);
      // With consent off (or the configuration switch off) nothing on the server runs
      // unattended, so there is nothing new to read on a timer; the tick skips the request.
      refreshTimer = setInterval(() => {
        const current = get().state;
        if (current?.enabled && current.consent) void get().loadState();
      }, STATE_REFRESH_MS);
    }
    let stopped = false;
    return () => {
      if (stopped) return;
      stopped = true;
      watchers -= 1;
      if (watchers > 0) return;
      if (onVisible !== null) document.removeEventListener("visibilitychange", onVisible);
      onVisible = null;
      if (refreshTimer !== null) clearInterval(refreshTimer);
      refreshTimer = null;
    };
  },
}));
