// 04-W2-03: global currency — mirrors app_config "currency"; one-shot auto-derive
// from the active i18n language on first run (after that, language changes do NOT
// change currency — the user owns the setting).
import { create } from "zustand";
import i18n from "@/i18n";
import { get, put } from "@/api/client"; // Decision D — named imports, no apiClient
import { deriveCurrencyFromLanguage, type CurrencyCode } from "@/lib/currency";

interface CurrencyStore {
  currency: CurrencyCode;
  hydrated: boolean;
  hydrate: () => Promise<void>;
  setCurrency: (c: CurrencyCode) => Promise<void>;
}

export const useCurrencyStore = create<CurrencyStore>((set, getState) => ({
  currency: "USD",
  hydrated: false,
  hydrate: async () => {
    if (getState().hydrated) return;
    try {
      const res = await get<{ success: boolean; value: string | null }>(
        "/api/system/app-config/currency"
      );
      if (res && res.value && typeof res.value === "string") {
        set({ currency: res.value as CurrencyCode, hydrated: true });
        return;
      }
      // First-run derive: read active i18n language, derive, persist back.
      const derived = deriveCurrencyFromLanguage(i18n.resolvedLanguage || "en");
      // Fire-and-forget — local state is set regardless.
      put("/api/system/app-config/currency", { value: derived }).catch(() => { /* ignore */ });
      set({ currency: derived, hydrated: true });
    } catch {
      set({ hydrated: true }); // mark hydrated so we don't retry on every render
    }
  },
  setCurrency: async (c: CurrencyCode) => {
    set({ currency: c });
    await put("/api/system/app-config/currency", { value: c });
  },
}));
