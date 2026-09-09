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
}

const DEFAULT_RELEASES = "https://github.com/ipmideck/IPMIDeck/releases";

/**
 * Update state and the packaged version history.
 *
 * The changelog is fetched once and kept: it is a file that shipped with the build, so it cannot
 * change while the page is open, and re-fetching it on every dialog open would make opening the
 * history feel slower than it is.
 *
 * Nothing here checks for a newer version on its own. `checkNow` is only ever called from a
 * button the operator pressed.
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
  },
}));
