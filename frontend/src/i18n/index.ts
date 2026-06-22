/** i18next init: browser-language detection + lazy per-language chunks; English bundled as the synchronous fallback. */

import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import resourcesToBackend from "i18next-resources-to-backend";

import en from "./locales/en/translation.json";
import { SUPPORTED_LNGS } from "./languages";

/**
 * Normalize a detected/cached language tag (navigator.language OR a stale
 * localStorage value) to a SUPPORTED_LNGS code BEFORE i18next resolves it.
 * Without this, `load: "currentOnly"` tries to load the exact regional tag
 * (e.g. "it-IT") which has no catalog and falls back to English (GAP-I18N-01).
 *
 * Rules:
 *  - lowercase the tag.
 *  - Chinese: zh-TW / zh-Hant* -> "en" (Simplified-only per CONTEXT D-01/D-03;
 *    Traditional Chinese is not a shipped catalog, so zh-TW falls back to en by
 *    design). All other zh* (zh, zh-cn, zh-sg, zh-hans*) -> "zh-Hans".
 *  - Otherwise take the primary subtag (before the first "-"); if it is in
 *    SUPPORTED_LNGS return that base code; else fall back to "en".
 */
function convertDetectedLanguage(lng: string): string {
  if (!lng) return "en";
  const lower = lng.toLowerCase();
  if (lower.startsWith("zh")) {
    // Traditional Chinese is not shipped -> English by design.
    if (lower.startsWith("zh-tw") || lower.startsWith("zh-hant")) return "en";
    // zh / zh-cn / zh-sg / zh-hans* -> canonical Simplified code.
    return "zh-Hans";
  }
  const primary = lower.split("-")[0];
  return (SUPPORTED_LNGS as readonly string[]).includes(primary) ? primary : "en";
}

i18n
  .use(LanguageDetector)
  // Lazy-load every non-bundled language as a separate Vite chunk.
  .use(
    resourcesToBackend(
      (lng: string, ns: string) => import(`./locales/${lng}/${ns}.json`)
    )
  )
  .use(initReactI18next)
  .init({
    fallbackLng: "en",
    supportedLngs: SUPPORTED_LNGS,
    // NOTE: `nonExplicitSupportedLngs` MUST stay false. When true, i18next's
    // isSupportedCode() reduces a tag to its primary subtag before the
    // supportedLngs check (e.g. "zh-Hans" -> "zh"). Because our only script-
    // subtag code is "zh-Hans" (and "zh" is NOT in SUPPORTED_LNGS), that
    // reduction made i18next REJECT "zh-Hans" from the resolve hierarchy, so
    // the Simplified-Chinese catalog was never requested/loaded (the resolve
    // chain collapsed to ["en"]). All 11 lowercase single-subtag codes were
    // unaffected because their primary subtag equals the full code.
    // Regional normalization (zh-CN / zh-SG / zh-Hans-CN -> zh-Hans, zh-TW -> en)
    // is handled explicitly by convertDetectedLanguage below, so this flag is
    // redundant for that purpose and harmful for script-subtag codes.
    nonExplicitSupportedLngs: false,
    load: "currentOnly",
    ns: ["translation"],
    defaultNS: "translation",
    // English is statically bundled so the very first paint never blocks on a fetch.
    resources: { en: { translation: en } },
    partialBundledLanguages: true,
    interpolation: { escapeValue: false },
    react: { useSuspense: false },
    detection: {
      order: ["localStorage", "navigator"],
      lookupLocalStorage: "ipmideck-language",
      caches: ["localStorage"],
      convertDetectedLanguage,
    },
  });

// Keep <html lang> in sync with the active language (a11y/SEO). Runs on every
// change and once now for the initial resolved language.
function syncHtmlLang(lng: string) {
  if (typeof document !== "undefined") {
    document.documentElement.lang = lng;
  }
}
i18n.on("languageChanged", syncHtmlLang);
syncHtmlLang(i18n.resolvedLanguage ?? i18n.language ?? "en");

export default i18n;
