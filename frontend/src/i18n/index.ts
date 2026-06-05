/** i18next init: browser-language detection + lazy per-language chunks; English bundled as the synchronous fallback. */

import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import resourcesToBackend from "i18next-resources-to-backend";

import en from "./locales/en/translation.json";
import { SUPPORTED_LNGS } from "./languages";

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
    // zh-CN / zh-SG / zh-Hans-CN all resolve to zh-Hans (front/back agreement); zh-TW falls back to en by design.
    nonExplicitSupportedLngs: true,
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
      lookupLocalStorage: "ipmilink-language",
      caches: ["localStorage"],
    },
  });

export default i18n;
