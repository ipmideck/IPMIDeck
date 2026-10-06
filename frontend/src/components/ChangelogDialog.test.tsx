import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

/**
 * The version history dialog and the control that opens it.
 *
 * A component test rather than a browser pass: the running app redirects to the setup wizard
 * until a server exists, and vitest is already part of the CI gate whereas a browser driver is
 * neither in the repo nor in CI.
 */

const changelogPayload = {
  success: true,
  current_version: "2.0.1",
  changelog_url: "https://example.invalid/changelog",
  releases_url: "https://example.invalid/releases",
  entries: [
    {
      version: "Unreleased",
      date: null,
      is_security: true,
      is_unreleased: true,
      body: "### Security\n\n- Fixed a serious hole.",
    },
    {
      version: "2.0.1",
      date: "2026-07-25",
      is_security: false,
      is_unreleased: false,
      body: "### Fixed\n\n- An ordinary fix.",
    },
  ],
};

const statePayload = {
  success: true,
  enabled: true,
  consent: false,
  current_version: "2.0.1",
  latest_version: null,
  update_available: false,
  is_security: false,
  release_url: "https://example.invalid/releases",
  install_method: "git",
  checked_at: null,
  error: null,
};

vi.mock("@/api/client", () => ({
  get: vi.fn((path: string) => {
    if (path === "/api/updates/changelog") return Promise.resolve(changelogPayload);
    if (path === "/api/updates/state") return Promise.resolve(statePayload);
    return Promise.resolve({});
  }),
  post: vi.fn(() => Promise.resolve({ success: true })),
  put: vi.fn(() => Promise.resolve({ success: true })),
  del: vi.fn(() => Promise.resolve({ success: true })),
  setUnauthorizedHandler: vi.fn(),
  api: vi.fn(() => Promise.resolve({})),
}));

import { get } from "@/api/client";
import { ChangelogDialog } from "@/components/ChangelogDialog";
import { VersionButton } from "@/components/layout/VersionButton";
import { useUIOverlayStore } from "@/stores/ui-overlay-store";
import { useUpdateStore } from "@/stores/update-store";

function resetStores() {
  useUIOverlayStore.setState({ changelogOpen: false });
  useUpdateStore.setState({
    state: null,
    stateLoading: false,
    entries: [],
    changelogUrl: "",
    releasesUrl: "https://github.com/ipmideck/IPMIDeck/releases",
    changelogLoaded: false,
    changelogLoading: false,
    changelogError: false,
    checking: false,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  resetStores();
});

afterEach(() => {
  cleanup();
});

describe("the version history dialog", () => {
  it("stays closed until something opens it", () => {
    render(<ChangelogDialog />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("loads and renders every entry once opened", async () => {
    render(<ChangelogDialog />);
    useUIOverlayStore.getState().setChangelogOpen(true);
    await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy());
    await waitFor(() => expect(screen.getByText("2.0.1")).toBeTruthy());
    expect(screen.getByText("An ordinary fix.")).toBeTruthy();
    expect(screen.getByText("Fixed a serious hole.")).toBeTruthy();
  });

  it("reads the history from the packaged file, never from a lookup", async () => {
    render(<ChangelogDialog />);
    useUIOverlayStore.getState().setChangelogOpen(true);
    await waitFor(() => expect(get).toHaveBeenCalledWith("/api/updates/changelog"));
    const paths = (get as unknown as { mock: { calls: string[][] } }).mock.calls.map((c) => c[0]);
    expect(paths).not.toContain("/api/updates/check");
  });

  it("marks a security release apart from an ordinary one", async () => {
    render(<ChangelogDialog />);
    useUIOverlayStore.getState().setChangelogOpen(true);
    await waitFor(() => expect(screen.getByText("2.0.1")).toBeTruthy());

    // Scoped to each entry's header row: the badge word is the non-colour carrier of "this is a
    // security release", and the body of an entry may legitimately contain the same word as a
    // group heading, so a document-wide text match would not distinguish the two.
    const badge = /updates\.securityRelease|^Security$/i;
    const securityEntry = screen
      .getByText(/updates\.unreleased|^Unreleased$/i)
      .closest("header") as HTMLElement;
    const ordinaryEntry = screen.getByText("2.0.1").closest("header") as HTMLElement;

    expect(within(securityEntry).getByText(badge)).toBeTruthy();
    expect(within(ordinaryEntry).queryByText(badge)).toBeNull();
  });

  it("shows nothing about a newer version when there is none", async () => {
    useUpdateStore.setState({ state: { ...statePayload } });
    render(<ChangelogDialog />);
    useUIOverlayStore.getState().setChangelogOpen(true);
    await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy());
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("announces a newer version when there is one", async () => {
    useUpdateStore.setState({
      state: { ...statePayload, latest_version: "9.9.9", update_available: true },
    });
    render(<ChangelogDialog />);
    useUIOverlayStore.getState().setChangelogOpen(true);
    await waitFor(() => expect(screen.getByRole("status")).toBeTruthy());
  });

  it("offers a way out when the history cannot be read", async () => {
    useUpdateStore.setState({ changelogLoaded: true, changelogError: true });
    render(<ChangelogDialog />);
    useUIOverlayStore.getState().setChangelogOpen(true);
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getByRole("button", { name: /common\.retry|retry/i })).toBeTruthy();
  });

  it("says so plainly when the history is empty rather than showing a blank panel", async () => {
    useUpdateStore.setState({ changelogLoaded: true, entries: [] });
    render(<ChangelogDialog />);
    useUIOverlayStore.getState().setChangelogOpen(true);
    await waitFor(() =>
      expect(screen.getByText(/updates\.changelogEmpty|no version history/i)).toBeTruthy(),
    );
  });

  it("draws an upgrade note as a note, without the markdown markers", async () => {
    useUpdateStore.setState({
      changelogLoaded: true,
      entries: [
        {
          version: "Unreleased",
          date: null,
          is_security: false,
          is_unreleased: true,
          body: [
            "> ### Upgrading logs everyone out",
            ">",
            "> **Log in again** once after updating, then run `ipmideck doctor`.",
            ">",
            "> ```yaml",
            "> server:",
            ">   trusted_origins: []",
            "> ```",
            "",
            "### Fixed",
            "",
            "- An ordinary fix.",
          ].join("\n"),
        },
      ],
    });
    render(<ChangelogDialog />);
    useUIOverlayStore.getState().setChangelogOpen(true);
    const heading = await screen.findByRole("heading", { name: "Upgrading logs everyone out" });
    const note = heading.closest("aside") as HTMLElement;
    expect(note).toBeTruthy();
    expect(within(note).getByText("Log in again").tagName).toBe("STRONG");
    expect(within(note).getByText("ipmideck doctor").tagName).toBe("CODE");
    expect(note.querySelector("pre")?.textContent).toBe("server:\n  trusted_origins: []");
    expect(note.textContent).not.toMatch(/>|###|\*\*|```/);
    // The section after the note is not drawn inside it.
    expect(within(note).queryByText("An ordinary fix.")).toBeNull();
    expect(screen.getByText("An ordinary fix.")).toBeTruthy();
  });

  it("boxes the Upgrade notes group the same way", async () => {
    useUpdateStore.setState({
      changelogLoaded: true,
      entries: [
        {
          version: "Unreleased",
          date: null,
          is_security: false,
          is_unreleased: true,
          body: "### Upgrade notes\n\n- **Log in again once.** Nothing is lost.\n\n### Fixed\n\n- **A fix.**",
        },
      ],
    });
    render(<ChangelogDialog />);
    useUIOverlayStore.getState().setChangelogOpen(true);
    const heading = await screen.findByRole("heading", { name: "Upgrade notes" });
    const note = heading.closest("aside") as HTMLElement;
    expect(within(note).getByText("Log in again once.")).toBeTruthy();
    expect(within(note).queryByText("A fix.")).toBeNull();
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    render(<ChangelogDialog />);
    useUIOverlayStore.getState().setChangelogOpen(true);
    await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy());
    await user.keyboard("{Escape}");
    await waitFor(() => expect(useUIOverlayStore.getState().changelogOpen).toBe(false));
  });

  it("counts as an open overlay so page shortcuts do not fire underneath it", () => {
    useUIOverlayStore.getState().setChangelogOpen(true);
    expect(useUIOverlayStore.getState().anyOverlayOpen()).toBe(true);
  });
});

describe("the sidebar version control", () => {
  it("shows the running version and opens the history when pressed", async () => {
    const user = userEvent.setup();
    render(<VersionButton />);
    await waitFor(() => expect(screen.getByText("v2.0.1")).toBeTruthy());
    await user.click(screen.getByRole("button"));
    expect(useUIOverlayStore.getState().changelogOpen).toBe(true);
  });

  it("carries no update marker while the instance is current", async () => {
    render(<VersionButton />);
    await waitFor(() => expect(screen.getByText("v2.0.1")).toBeTruthy());
    expect(screen.queryByText(/updates\.new|^new$/i)).toBeNull();
  });

  it("leaves a newer version to the upgrade button beside it", async () => {
    useUpdateStore.setState({
      state: { ...statePayload, latest_version: "9.9.9", update_available: true },
    });
    render(<VersionButton />);
    await waitFor(() => expect(screen.getByText("v2.0.1")).toBeTruthy());
    expect(screen.queryByText(/updates\.new|^new$/i)).toBeNull();
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("reads state without ever triggering a lookup", async () => {
    render(<VersionButton />);
    await waitFor(() => expect(get).toHaveBeenCalledWith("/api/updates/state"));
    const paths = (get as unknown as { mock: { calls: string[][] } }).mock.calls.map((c) => c[0]);
    expect(paths).not.toContain("/api/updates/check");
  });
});
