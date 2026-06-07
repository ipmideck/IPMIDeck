import { afterEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
// Real i18n singleton — RESEARCH Pitfall 5: do NOT mock react-i18next/i18next.
// LanguageSelect reads i18n.resolvedLanguage and renders activeEntry.native, so
// driving the real singleton with changeLanguage is the only honest way to guard
// the 02.2 GAP-I18N-04 active-label regression.
import i18n from "@/i18n";
import { LanguageSelect } from "@/components/LanguageSelect";

afterEach(async () => {
  // Reset to English so language state never leaks between tests / suites.
  await i18n.changeLanguage("en");
});

describe("LanguageSelect active-language label (GAP-I18N-04 guard)", () => {
  it("shows the Italian native name when the active language is 'it'", async () => {
    await i18n.changeLanguage("it");
    render(<LanguageSelect />);
    // The trigger button renders activeEntry.native — must reflect the resolved
    // language, not a hardcoded default.
    expect(screen.getByText("Italiano")).toBeInTheDocument();
  });

  it("shows the German native name when the active language is 'de'", async () => {
    await i18n.changeLanguage("de");
    render(<LanguageSelect />);
    // A second language proves the label tracks the active language rather than
    // a fixed value (the original GAP-I18N-04 bug always showed the default).
    expect(screen.getByText("Deutsch")).toBeInTheDocument();
  });
});
