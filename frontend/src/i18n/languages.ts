/** Supported-language metadata: native display names + Intl locale tags. */

export const LANGUAGES = [
  { code: "en", native: "English", intl: "en-US" },
  { code: "de", native: "Deutsch", intl: "de" },
  { code: "fr", native: "Français", intl: "fr" },
  { code: "es", native: "Español", intl: "es" },
  { code: "it", native: "Italiano", intl: "it" },
  { code: "pt", native: "Português", intl: "pt" },
  { code: "nl", native: "Nederlands", intl: "nl" },
  { code: "ru", native: "Русский", intl: "ru" },
  { code: "pl", native: "Polski", intl: "pl" },
  { code: "zh-Hans", native: "简体中文", intl: "zh-Hans" },
  { code: "ja", native: "日本語", intl: "ja" },
  { code: "ko", native: "한국어", intl: "ko" },
] as const;

export const SUPPORTED_LNGS = LANGUAGES.map((l) => l.code);

export function intlLocale(lng?: string | null): string {
  return LANGUAGES.find((l) => l.code === lng)?.intl ?? "en-US";
}
