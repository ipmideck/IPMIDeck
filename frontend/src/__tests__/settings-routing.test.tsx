import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";

/**
 * Wave-0 net-new test scaffolding (D-09, 06-01 Task 4).
 *
 * Guards the foundation routing contract that the per-page Settings rebuild (06-08)
 * and the onboarding tour repoint (D-14) depend on:
 *   1. The /settings index redirect lands on the Servers section (/settings/servers),
 *      so the four bare-`/settings` call-sites (Sidebar/MobileNavDrawer/CommandPalette/
 *      Dashboard) always arrive at a populated section.
 *   2. A deep section path (/settings/appearance) is reachable — the foundation
 *      guarantee the tour's language step relies on.
 *
 * The real SettingsPage is too heavy to mount in jsdom (it fetches /api/* via several
 * stores on mount), so per the plan this exercises the ROUTING WRAPPER with a faithful
 * reproduction of the App.tsx `/settings/*` route + the SettingsPage index-redirect
 * logic — asserting on the RESOLVED path/section, not on monolith internals. The
 * redirect logic (path === "/settings" -> <Navigate replace to="/settings/servers">)
 * is byte-identical to the foundation code in App.tsx and SettingsPage.tsx.
 *
 * 06-08 extends this file with the three brief-mandated tests (deep-link-focus,
 * tour-reachability, back-button-traversal) once the two-pane + sections exist.
 */

/** Mirrors SettingsPage's index redirect + single-panel section passthrough. */
function SettingsRouteShell() {
  const location = useLocation();
  // Same guard as SettingsPage.tsx: bare /settings -> default landing section.
  if (location.pathname === "/settings" || location.pathname === "/settings/") {
    return <Navigate replace to="/settings/servers" />;
  }
  // Until 06-08 splits the monolith, any section path renders the same shell; the
  // resolved section is derived from the URL (this is what the test asserts on).
  const section = location.pathname.replace(/^\/settings\/?/, "") || "(none)";
  return <div data-testid="settings-section">{section}</div>;
}

/** Mirrors the App.tsx wildcard route `<Route path="/settings/*" ...>`. */
function renderAt(initialPath: string) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/settings/*" element={<SettingsRouteShell />} />
      </Routes>
    </MemoryRouter>
  );
}

afterEach(() => {
  cleanup();
});

describe("Settings routing foundation (06-01 / D-13 blocker #2)", () => {
  it("redirects bare /settings to the Servers section (/settings/servers)", () => {
    renderAt("/settings");
    // The index redirect resolves and the Servers section renders.
    expect(screen.getByTestId("settings-section")).toHaveTextContent("servers");
  });

  it("resolves the deep /settings/appearance section path (tour-repoint guarantee)", () => {
    renderAt("/settings/appearance");
    // The Appearance section path is reachable and is NOT bounced to servers.
    expect(screen.getByTestId("settings-section")).toHaveTextContent("appearance");
  });
});
