/**
 * Thin in-memory mirror of i18next's active language.
 *
 * Intentionally NOT wrapped in Zustand storage middleware: the i18next
 * browser-languagedetector already owns the `ipmilink-language` localStorage
 * key (caches: ["localStorage"]). A second writer against the same key would
 * cause a hydration race that flips the language on reload. i18next is the
 * single source of truth; this store only reflects it for components that
 * prefer a store selector.
 */

import { create } from "zustand";
import i18n from "@/i18n";

interface LanguageState {
  language: string;
  setLanguage: (lng: string) => void;
}

export const useLanguageStore = create<LanguageState>((set) => ({
  language: i18n.resolvedLanguage ?? i18n.language ?? "en",
  setLanguage: (lng) => {
    i18n.changeLanguage(lng);
    set({ language: lng });
  },
}));

// Keep the mirror in sync when i18next resolves/changes the active language.
i18n.on("languageChanged", (lng) => useLanguageStore.setState({ language: lng }));
