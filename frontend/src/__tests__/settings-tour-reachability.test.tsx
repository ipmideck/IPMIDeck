import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import "@/i18n";

/**
 * Net-new tour-reachability test (D-09 / D-14 — the third Wave-0 Settings test,
 * after settings-routing + settings-deeplink).
 *
 * Contract under test: the first-login OnboardingTour's language step repoints its
 * before-hook navigation to `/settings/appearance` (06-09) and then awaits
 * `[data-tour="language-select"]`. That anchor lives in the Appearance section
 * after the 06-08 two-pane split. This test proves the tour's target resolves at
 * the repointed path: mounting the Settings route subtree at `/settings/appearance`
 * renders the Appearance section and `[data-tour="language-select"]` is present in
 * the document. If this anchor ever moves or is renamed, the tour's language step
 * would silently skip — so this is the guardrail for that link.
 *
 * Mirrors settings-deeplink.test.tsx: the real SettingsPage mounts stores that
 * fetch /api/*, so the API client + connection store are mocked; the routing +
 * Appearance render under test is real. The real @/i18n singleton (English bundled
 * synchronously) supplies the section's t() strings.
 */

// Mock the API client so store mounts don't hit the network. /api/servers must
// return a `servers` array; /api/health a version — both consumed by the shell.
vi.mock("@/api/client", () => ({
  get: vi.fn((path: string) => {
    if (path === "/api/servers") return Promise.resolve({ servers: [] });
    if (path === "/api/health") return Promise.resolve({ version: "0.0.0-test" });
    return Promise.resolve({ value: null });
  }),
  post: vi.fn(() => Promise.resolve({ success: true })),
  put: vi.fn(() => Promise.resolve({ success: true })),
  del: vi.fn(() => Promise.resolve({ success: true })),
  setUnauthorizedHandler: vi.fn(),
  api: vi.fn(() => Promise.resolve({})),
}));

// Backend online so nothing is offline-gated and the panel renders normally.
vi.mock("@/stores/connection-store", () => ({
  useBackendOnline: () => true,
  useConnectionStore: (selector: (s: { wsStatus: string }) => unknown) =>
    selector({ wsStatus: "connected" }),
}));

import SettingsPage from "@/pages/SettingsPage";

function renderAt(initialPath: string) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/settings/*" element={<SettingsPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  // Desktop viewport so the two-pane panel renders (not the mobile master list).
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Settings tour-reachability (D-14 — language step lands /settings/appearance)", () => {
  it("renders the Appearance section with [data-tour=\"language-select\"] at /settings/appearance", async () => {
    renderAt("/settings/appearance");
    // The tour's before-hook navigates to /settings/appearance and awaits this
    // exact anchor before presenting the language step; assert it resolves there.
    await waitFor(() => {
      expect(document.querySelector('[data-tour="language-select"]')).not.toBeNull();
    });
  });

  it("does NOT expose the language anchor on the default Servers section", async () => {
    // Sanity guard: bare /settings desktop-redirects to /settings/servers, which
    // has no language control — proving the tour MUST target the Appearance route
    // (the reason the before-hook was repointed off bare /settings in 06-09).
    renderAt("/settings/servers");
    await new Promise((r) => setTimeout(r, 50));
    expect(document.querySelector('[data-tour="language-select"]')).toBeNull();
  });
});
