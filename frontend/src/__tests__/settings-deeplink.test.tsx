import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { useServerStore, type Server } from "@/stores/server-store";

/**
 * Net-new deep-link-focus test (D-09 / brief Blocker #1).
 *
 * Asserts the production contract that the dashboard tariff CTAs depend on:
 * rendering at `/settings#server-{id}-cost` selects the Servers section, opens
 * that server's edit form, and focuses the cost input `server-{id}-cost`. The
 * regex `^#server-(.+)-cost$` and the input id are preserved verbatim across the
 * monolith->two-pane refactor; the undefined/new guards must short-circuit.
 *
 * The real SettingsPage mounts several stores that fetch /api/* — those are
 * mocked so the page renders in jsdom; the routing + deep-link logic under test
 * is real.
 */

// Synthetic test server — hoisted so the api mock factory can reference it.
// id is synthetic (no real hardware identifier) and host is RFC5737 (CLAUDE.md).
const TEST_SERVER: Server = vi.hoisted(() => ({
  id: "test-srv-0001",
  name: "Test BMC",
  description: "",
  host: "192.0.2.10",
  port: 623,
  vendor: "dell",
  color: "#3b82f6",
  poll_interval: 30,
  fanpilot_enabled: false,
  is_online: true,
  last_seen: null,
  cost_per_kwh: null,
})) as Server;

// Mock the API client so store mounts don't hit the network. The /api/servers
// GET must return a `servers` array (loadServers calls setServers(data.servers));
// returning {} would set servers=undefined and crash unrelated consumers.
vi.mock("@/api/client", () => ({
  get: vi.fn((path: string) => {
    if (path === "/api/servers") return Promise.resolve({ servers: [TEST_SERVER] });
    return Promise.resolve({ value: null });
  }),
  post: vi.fn(() => Promise.resolve({ success: true })),
  put: vi.fn(() => Promise.resolve({ success: true })),
  del: vi.fn(() => Promise.resolve({ success: true })),
  setUnauthorizedHandler: vi.fn(),
  api: vi.fn(() => Promise.resolve({})),
}));

// Backend online so mutation controls are enabled and nothing is offline-gated.
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
    </MemoryRouter>
  );
}

beforeEach(() => {
  // jsdom does not implement scrollIntoView; the deep-link consumer calls it
  // before focus(). Stub it so the focus step under test runs (production code
  // is unchanged — this is purely a jsdom capability gap).
  if (!("scrollIntoView" in HTMLElement.prototype)) {
    (HTMLElement.prototype as unknown as { scrollIntoView: () => void }).scrollIntoView = vi.fn();
  } else {
    vi.spyOn(HTMLElement.prototype, "scrollIntoView").mockImplementation(() => {});
  }
  // Desktop viewport so isMobile=false -> two-pane (not the mobile master list).
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
  // Seed the server store with the deep-link target.
  useServerStore.setState({ servers: [TEST_SERVER], loaded: true, contextServerId: TEST_SERVER.id });
});

afterEach(() => {
  cleanup();
  useServerStore.setState({ servers: [], loaded: false, contextServerId: null });
  vi.clearAllMocks();
});

describe("Settings deep-link focus (D-13 Blocker #1)", () => {
  it("focuses the cost input for /settings#server-{id}-cost", async () => {
    renderAt(`/settings#server-${TEST_SERVER.id}-cost`);
    await waitFor(() => {
      const el = document.getElementById(`server-${TEST_SERVER.id}-cost`);
      expect(el).not.toBeNull();
      expect(document.activeElement).toBe(el);
    });
  });

  it("does NOT open a blank form for the #server-undefined-cost guard", async () => {
    renderAt("/settings#server-undefined-cost");
    // Give effects a tick; the guard must short-circuit (no cost input rendered
    // for an 'undefined' id, and no edit form for a non-existent server).
    await new Promise((r) => setTimeout(r, 50));
    expect(document.getElementById("server-undefined-cost")).toBeNull();
  });

  it("does NOT open a blank form for the #server-new-cost guard", async () => {
    renderAt("/settings#server-new-cost");
    await new Promise((r) => setTimeout(r, 50));
    expect(document.getElementById("server-new-cost")).toBeNull();
  });
});
