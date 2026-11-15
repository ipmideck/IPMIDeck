// How dates and times are displayed — mirrors the app_config row "display.datetime" (a JSON
// string). Stored on the server so the choice follows the user to every browser and survives
// restarts. A missing row means defaults, and reading never writes one back.
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { create } from "zustand";
import { get, put } from "@/api/client";
import { intlLocale } from "@/i18n/languages";
import {
  DEFAULT_DISPLAY_PREFS,
  activeTimeZone,
  formatDate,
  formatDateTime,
  formatTime,
  sanitizeDisplayPrefs,
  type DisplayPrefs,
  type SiteStyle,
} from "@/lib/datetime";

const KEY_URL = "/api/system/app-config/display.datetime";

interface DisplayPrefsStore {
  prefs: DisplayPrefs;
  hydrated: boolean;
  hydrate: () => Promise<void>;
  /** Optimistic: applies at once, reverts and rejects when the server refuses it. */
  setPrefs: (next: DisplayPrefs) => Promise<void>;
}

export const useDisplayPrefsStore = create<DisplayPrefsStore>((set, getState) => ({
  prefs: { ...DEFAULT_DISPLAY_PREFS },
  hydrated: false,
  hydrate: async () => {
    if (getState().hydrated) return;
    try {
      const res = await get<{ success: boolean; value: unknown }>(KEY_URL);
      // A choice made while the read was in flight is newer than what the read returned.
      if (getState().hydrated) return;
      const prefs =
        res && res.success && res.value != null
          ? sanitizeDisplayPrefs(res.value)
          : { ...DEFAULT_DISPLAY_PREFS };
      set({ prefs, hydrated: true });
    } catch {
      set({ hydrated: true }); // keep defaults; do not retry on every render
    }
  },
  setPrefs: async (next: DisplayPrefs) => {
    const previous = getState().prefs;
    set({ prefs: next, hydrated: true });
    try {
      const res = await put<{ success: boolean }>(KEY_URL, { value: JSON.stringify(next) });
      if (!res || res.success !== true) throw new Error("display.datetime not saved");
    } catch (err) {
      set({ prefs: previous });
      throw err;
    }
  },
}));

export interface DateTimeFormat {
  formatTime: (value: string | number | Date, site: SiteStyle) => string;
  formatDate: (value: string | number | Date) => string;
  formatDateTime: (value: string | number | Date, site: SiteStyle) => string;
  /** The zone actually in use, e.g. "America/New_York". */
  timeZone: string;
}

/**
 * Formatters bound to the saved preference and the interface language. Components re-render
 * when either changes. browserLocale uses the browser's own locale instead of the language.
 */
export function useDateTimeFormat(opts?: { browserLocale?: boolean }): DateTimeFormat {
  const { i18n } = useTranslation();
  const prefs = useDisplayPrefsStore((s) => s.prefs);
  const locale = opts?.browserLocale ? undefined : intlLocale(i18n.resolvedLanguage);
  return useMemo(() => {
    const ctx = { locale, prefs };
    return {
      formatTime: (value, site) => formatTime(value, ctx, site),
      formatDate: (value) => formatDate(value, ctx),
      formatDateTime: (value, site) => formatDateTime(value, ctx, site),
      timeZone: activeTimeZone(prefs),
    };
  }, [locale, prefs]);
}
