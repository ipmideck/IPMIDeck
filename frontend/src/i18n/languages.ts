/** Supported-language metadata: native display names + Intl locale tags. */

export const LANGUAGES = [
  { code: "en", native: "English", intl: "en-US", country: "GB" },
  { code: "de", native: "Deutsch", intl: "de", country: "DE" },
  { code: "fr", native: "Français", intl: "fr", country: "FR" },
  { code: "es", native: "Español", intl: "es", country: "ES" },
  { code: "it", native: "Italiano", intl: "it", country: "IT" },
  { code: "pt", native: "Português", intl: "pt", country: "PT" },
  { code: "nl", native: "Nederlands", intl: "nl", country: "NL" },
  { code: "ru", native: "Русский", intl: "ru", country: "RU" },
  { code: "pl", native: "Polski", intl: "pl", country: "PL" },
  { code: "zh-Hans", native: "简体中文", intl: "zh-Hans", country: "CN" },
  { code: "ja", native: "日本語", intl: "ja", country: "JP" },
  { code: "ko", native: "한국어", intl: "ko", country: "KR" },
] as const;

export const SUPPORTED_LNGS = LANGUAGES.map((l) => l.code);

export function intlLocale(lng?: string | null): string {
  return LANGUAGES.find((l) => l.code === lng)?.intl ?? "en-US";
}
