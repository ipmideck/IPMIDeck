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
 * When, counted from the moment the unattended check is switched on, the page re-reads the state.
 * Switching it on starts the first check at once on the server. That check may make two lookups
 * of up to six seconds each, and on a slow link it can take longer than one read would wait, so
 * the page reads more than once and stops as soon as a read shows that the check has finished.
 */
export const FIRST_CHECK_READS_MS = [15 * 1000, 30 * 1000, 60 * 1000];

// Shared by every caller of watchState: one visibility listener and one interval, however many
// version buttons are mounted (the sidebar's and the mobile drawer's can be at the same time).
let watchers = 0;
let refreshTimer: ReturnType<typeof setInterval> | null = null;
let onVisible: (() => void) | null = null;
// The reads after consent is given. Kept apart from the watchers because they belong to the
// answer, not to whichever component happens to be mounted when they fire. The run number lets a
// read that was already on its way when the answer changed see that it must not book another.
let firstCheckTimer: ReturnType<typeof setTimeout> | null = null;
let firstCheckRun = 0;

function stopFirstCheckReads() {
  firstCheckRun += 1;
  if (firstCheckTimer !== null) clearTimeout(firstCheckTimer);
  firstCheckTimer = null;
}

// Which answer about the update state is newest. A read takes a ticket when it starts; a check,
// and a change of consent, take one when they finish, because what they leave behind is as new as
// that moment. A read that comes back holding an older ticket than the answer on screen was served
// from what the server had before that answer existed, so it is dropped rather than shown.
let ticket = 0;
let shownTicket = 0;

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
    const mine = ++ticket;
    set({ stateLoading: true });
    try {
      const body = await apiGet<UpdateState & { success: boolean }>("/api/updates/state");
      if (mine < shownTicket) {
        // A newer answer (a Check now result, a change of consent, a later read) arrived while
        // this one was on its way; showing this one would put the older answer back on screen.
        set({ stateLoading: false });
        return;
      }
      shownTicket = mine;
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
      shownTicket = ++ticket;
      set({ state: merged, checking: false });
      return merged;
    } catch {
      set({ checking: false });
      return null;
    }
  },

  setConsent: async (enabled: boolean) => {
    // Taken before the answer is sent: the server starts the first check as soon as it has it.
    const checkedBefore = get().state?.checked_at ?? null;
    await put("/api/updates/consent", { enabled });
    const previous = get().state;
    if (previous) {
      // A read already on its way may carry the answer from before this one, undoing the switch.
      shownTicket = ++ticket;
      set({ state: { ...previous, consent: enabled } });
    }
    stopFirstCheckReads();
    if (!enabled) return;

    // The first check has just started on the server. Without these reads its result would only
    // appear on the next hourly tick, which reads as "nothing happened". They only ever read: the
    // check is already running, and asking for another is a person's action, not a timer's.
    const run = firstCheckRun;
    const startedAt = Date.now();
    const finished = () => (get().state?.checked_at ?? null) !== checkedBefore;
    const readAt = (step: number) => {
      if (step >= FIRST_CHECK_READS_MS.length) return;
      const wait = Math.max(0, FIRST_CHECK_READS_MS[step] - (Date.now() - startedAt));
      firstCheckTimer = setTimeout(() => {
        firstCheckTimer = null;
        // The result is in, brought by the previous of these reads or by another one (the tab
        // shown again, say): there is nothing left to wait for.
        if (finished()) return;
        void get()
          .loadState()
          .then(() => {
            if (run === firstCheckRun) readAt(step + 1);
          });
      }, wait);
    };
    readAt(0);
  },

  watchState: () => {
    watchers += 1;
    if (watchers === 1) {
      // Coming back to the tab is when a stale badge would be noticed, and it also picks up a
      // check made from elsewhere (another browser, or the console key) while consent is off.
      // Neither this nor the timer below reads while Check now is running: its answer is on the
      // way, and a read made now could only return what that answer is about to replace.
      onVisible = () => {
        const { stateLoading, checking } = get();
        if (document.visibilityState === "visible" && !stateLoading && !checking) {
          void get().loadState();
        }
      };
      document.addEventListener("visibilitychange", onVisible);
      // With consent off (or the configuration switch off) nothing on the server runs
      // unattended, so there is nothing new to read on a timer; the tick skips the request.
      refreshTimer = setInterval(() => {
        const { state: current, checking } = get();
        if (current?.enabled && current.consent && !checking) void get().loadState();
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
