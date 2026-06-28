import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { useServerStore } from "@/stores/server-store";

/**
 * Net-new back-button-traversal test (D-09 / brief §8).
 *
 * Mobile (<768px) Settings is a URL-driven master-detail: bare /settings is the
 * section LIST; tapping a section navigates to /settings/<section> (panel + an
 * in-panel back); the back control returns to the list via history. The
 * transition is URL-driven (not a local boolean) — asserted on the resolved
 * pathname, which the dashboard/tour/deep-link flows all rely on.
 */

vi.mock("@/api/client", () => ({
  get: vi.fn(() => Promise.resolve({})),
  post: vi.fn(() => Promise.resolve({ success: true })),
  put: vi.fn(() => Promise.resolve({ success: true })),
  del: vi.fn(() => Promise.resolve({ success: true })),
  setUnauthorizedHandler: vi.fn(),
  api: vi.fn(() => Promise.resolve({})),
}));

vi.mock("@/stores/connection-store", () => ({
  useBackendOnline: () => true,
  useConnectionStore: (selector: (s: { wsStatus: string }) => unknown) =>
    selector({ wsStatus: "connected" }),
}));

import SettingsPage from "@/pages/SettingsPage";

/** Surfaces the resolved pathname so the test asserts on the URL, not internals. */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="pathname">{location.pathname}</div>;
}

function renderAt(initialPath: string) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <LocationProbe />
      <Routes>
        <Route path="/settings/*" element={<SettingsPage />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  // Mobile viewport: matches the (max-width: 767px) query -> isMobile=true.
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: /max-width:\s*767px/.test(query),
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
  useServerStore.setState({ servers: [], loaded: true, contextServerId: null });
});

afterEach(() => {
  cleanup();
  useServerStore.setState({ servers: [], loaded: false, contextServerId: null });
  vi.clearAllMocks();
});

describe("Settings mobile master-detail traversal (D-07 / D-13)", () => {
  it("list -> tap section -> panel -> in-panel back -> list (URL-driven)", async () => {
    const user = userEvent.setup();
    renderAt("/settings");

    // Master: bare /settings shows the section list (not redirected on mobile).
    await waitFor(() => {
      expect(screen.getByTestId("pathname")).toHaveTextContent("/settings");
    });
    // Tapping the Security row navigates to its panel.
    const securityRow = await screen.findByRole("button", { name: /security/i });
    await user.click(securityRow);

    await waitFor(() => {
      expect(screen.getByTestId("pathname")).toHaveTextContent("/settings/security");
    });

    // Detail: an in-panel back control is present; clicking it returns to the list.
    const backBtn = await screen.findByRole("button", { name: /back to settings/i });
    await user.click(backBtn);

    await waitFor(() => {
      expect(screen.getByTestId("pathname")).toHaveTextContent(/^\/settings$/);
    });
  });
});
