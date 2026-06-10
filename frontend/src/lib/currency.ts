// 04-W2-03: currency model — symbol map, language→currency derivation, Intl formatting.
export type CurrencyCode = "EUR" | "USD" | "GBP" | "JPY" | "KRW" | "CNY" | "PLN" | "RUB";

export const SUPPORTED_CURRENCIES: CurrencyCode[] = ["EUR", "USD", "GBP", "JPY", "KRW", "CNY", "PLN", "RUB"];

export const SYMBOL: Record<CurrencyCode, string> = {
  EUR: "€", USD: "$", GBP: "£", JPY: "¥", KRW: "₩", CNY: "¥", PLN: "zł", RUB: "₽",
};

// CONTEXT 04-W2-03 LOCKED map — verbatim
export const CURRENCY_BY_LANG: Record<string, CurrencyCode> = {
  it: "EUR", de: "EUR", fr: "EUR", es: "EUR", pt: "EUR", nl: "EUR",
  en: "USD",
  ja: "JPY",
  ko: "KRW",
  "zh-Hans": "CNY",
  pl: "PLN",
  ru: "RUB",
};

export function deriveCurrencyFromLanguage(lang: string): CurrencyCode {
  if (CURRENCY_BY_LANG[lang]) return CURRENCY_BY_LANG[lang];
  const base = lang.split("-")[0];
  if (CURRENCY_BY_LANG[base]) return CURRENCY_BY_LANG[base];
  return "USD";
}

export function formatCurrency(amount: number, currency: CurrencyCode, locale: string): string {
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(amount);
  } catch {
    return `${SYMBOL[currency] ?? currency} ${amount.toFixed(2)}`;
  }
}

export function currencyOptionLabel(c: CurrencyCode): string {
  return `${SYMBOL[c]} ${c}`;
}
