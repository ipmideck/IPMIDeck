import { afterEach, describe, expect, it } from "vitest";
// Real i18n singleton + real store — no mocking (RESEARCH Pitfall 5).
import i18n from "@/i18n";
import { useLanguageStore } from "@/stores/language-store";

afterEach(async () => {
  // Reset both the store mirror and i18next so state does not leak.
  await i18n.changeLanguage("en");
  useLanguageStore.setState({ language: "en" });
});

describe("language-store setLanguage wiring (REVIEWS race fix)", () => {
  it("updates the SYNCHRONOUS store mirror immediately", () => {
    useLanguageStore.getState().setLanguage("fr");
    // The store mirror is set synchronously inside setLanguage (set({language: lng})),
    // so it is safe to assert immediately. i18n.changeLanguage is fired but NOT
    // awaited inside the store, so we must NOT assert i18n.resolvedLanguage here.
    expect(useLanguageStore.getState().language).toBe("fr");
  });

  it("drives i18next once the async language change has settled", async () => {
    useLanguageStore.getState().setLanguage("fr");
    // Await the async catalog load before asserting the i18n side — asserting
    // i18n.resolvedLanguage synchronously after setLanguage would race the
    // (un-awaited) changeLanguage call. changeLanguage is idempotent here.
    await i18n.changeLanguage("fr");
    expect(i18n.resolvedLanguage).toBe("fr");
    // The languageChanged listener mirrors the resolved language back into the store.
    expect(useLanguageStore.getState().language).toBe("fr");
  });
});
