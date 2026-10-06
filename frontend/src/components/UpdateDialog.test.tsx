import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

/**
 * The newer version as the operator meets it: the upgrade button beside the logo, the toast,
 * and the dialog with its notes and its install.
 */

vi.mock("@/api/client", () => ({
  get: vi.fn(() => Promise.resolve({ success: true, phase: "idle" })),
  post: vi.fn(() => Promise.resolve({ success: false, error_code: "update_busy" })),
  put: vi.fn(),
  del: vi.fn(),
  api: vi.fn(),
  setUnauthorizedHandler: vi.fn(),
}));

vi.mock("sonner", () => {
  const toast = Object.assign(vi.fn(), { warning: vi.fn() });
  return { toast };
});

import { post } from "@/api/client";
import { toast } from "sonner";
import { UpdateDialog, updateGuideUrl } from "@/components/UpdateDialog";
import { UPDATE_TOAST_KEY, UpdateNotifier } from "@/components/UpdateNotifier";
import { UpgradeButton } from "@/components/layout/UpgradeButton";
import { useUIOverlayStore } from "@/stores/ui-overlay-store";
import { useUpdateInstallStore } from "@/stores/update-install-store";
import { useUpdateStore, type UpdateState, type UpgradePlan } from "@/stores/update-store";

const automatic: UpgradePlan = {
  automatic: true,
  mechanism: "pip",
  command: "python -m pip install --upgrade ipmideck==2.1.0",
  reason: null,
  restart: "automatic",
};

const base: UpdateState = {
  enabled: true,
  consent: true,
  current_version: "2.0.1",
  latest_version: "2.1.0",
  update_available: true,
  is_security: false,
  release_url: "https://example.invalid/releases/v2.1.0",
  install_method: "pip",
  checked_at: "2026-10-06T10:00:00Z",
  error: null,
  notes: "### Added\n\n- **A shiny thing.** It does what it says.",
  upgrade: automatic,
};

function withState(state: Partial<UpdateState> | null) {
  useUpdateStore.setState({ state: state === null ? null : { ...base, ...state } });
}

function openDialog() {
  render(<UpdateDialog />);
  useUIOverlayStore.getState().setUpdateOpen(true);
}

beforeEach(() => {
  vi.clearAllMocks();
  useUIOverlayStore.setState({ updateOpen: false, changelogOpen: false });
  useUpdateInstallStore.getState().reset();
  withState(null);
  try {
    localStorage.clear();
  } catch {
    /* no storage */
  }
});

afterEach(() => {
  cleanup();
  useUpdateInstallStore.getState().reset();
});

describe("the upgrade button beside the logo", () => {
  it("is absent while the instance is current", () => {
    withState({ update_available: false, latest_version: "2.0.1", upgrade: null });
    render(<UpgradeButton />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("appears for a newer version and opens the update dialog", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    withState({});
    render(<UpgradeButton onOpen={onOpen} />);
    const button = screen.getByRole("button", { name: "updateDialog.upgradeLabel" });
    await user.click(button);
    expect(useUIOverlayStore.getState().updateOpen).toBe(true);
    expect(onOpen).toHaveBeenCalled();
  });

  it("names a security release as one, not by colour alone", () => {
    withState({ is_security: true });
    render(<UpgradeButton />);
    expect(screen.getByRole("button", { name: "updateDialog.upgradeSecurityLabel" })).toBeTruthy();
  });

  it("is an icon only, so the name and version beside it keep their line", () => {
    withState({});
    render(<UpgradeButton />);
    expect(screen.getByRole("button").textContent).toBe("");
  });
});

describe("the update dialog", () => {
  it("shows the new version's notes and offers the install the server can do", async () => {
    withState({});
    openDialog();
    await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy());
    expect(screen.getByText("A shiny thing.")).toBeTruthy();
    expect(screen.getByText(/updateDialog\.backupFirst/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /updateDialog\.install$/ })).toBeTruthy();
  });

  it("links to the release when the notes could not be read", async () => {
    withState({ notes: null });
    openDialog();
    await waitFor(() => expect(screen.getByText(/updateDialog\.notesMissing/)).toBeTruthy());
    const links = screen.getAllByRole("link");
    expect(links.some((a) => a.getAttribute("href") === base.release_url)).toBe(true);
  });

  it("explains why it cannot install and gives the command instead", async () => {
    withState({
      install_method: "docker",
      upgrade: {
        automatic: false,
        mechanism: null,
        command: "docker compose pull && docker compose up -d",
        reason: "docker",
        restart: null,
      },
    });
    openDialog();
    await waitFor(() => expect(screen.getByText("updateDialog.reason.docker")).toBeTruthy());
    expect(screen.getByText("docker compose pull && docker compose up -d")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /updateDialog\.install$/ })).toBeNull();
    const guide = screen.getByRole("link", { name: /updateDialog\.guide/ });
    expect(guide.getAttribute("href")).toMatch(/^https:\/\/docs\.ipmideck\.com\/[\w-]+\/update-from-web-ui$/);
  });

  it("opens the guide in the reader's language, or in English when the docs lack it", () => {
    expect(updateGuideUrl("it")).toBe("https://docs.ipmideck.com/it/update-from-web-ui");
    expect(updateGuideUrl("zh-Hans")).toBe("https://docs.ipmideck.com/zh-Hans/update-from-web-ui");
    expect(updateGuideUrl("xx")).toBe("https://docs.ipmideck.com/en/update-from-web-ui");
    expect(updateGuideUrl(undefined)).toBe("https://docs.ipmideck.com/en/update-from-web-ui");
  });

  it("does not offer a command that pip would refuse on a system Python", async () => {
    withState({
      upgrade: {
        automatic: false,
        mechanism: null,
        command: "python3 -m pip install --upgrade ipmideck==2.1.0",
        reason: "system_python",
        restart: null,
      },
    });
    openDialog();
    await waitFor(() => expect(screen.getByText("updateDialog.reason.system_python")).toBeTruthy());
    expect(screen.queryByText(/pip install/)).toBeNull();
  });

  it("starts the install and shows a refusal with its reason", async () => {
    const user = userEvent.setup();
    withState({});
    openDialog();
    await user.click(await screen.findByRole("button", { name: /updateDialog\.install$/ }));
    expect(post).toHaveBeenCalledWith("/api/updates/install");
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getByText("updateDialog.reason.busy")).toBeTruthy();
    expect(screen.getByRole("button", { name: /updateDialog\.retry/ })).toBeTruthy();
  });

  it("stays open while the install runs, and shows where it is", async () => {
    const user = userEvent.setup();
    withState({});
    useUpdateInstallStore.setState({ snapshot: { phase: "installing", target: "2.1.0" } });
    openDialog();
    await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy());
    const current = document.querySelector('[aria-current="step"]');
    expect(current?.textContent).toContain("updateDialog.steps.install");
    expect(screen.getByRole("status").textContent).toContain("updateDialog.keepRunning");
    await user.keyboard("{Escape}");
    expect(useUIOverlayStore.getState().updateOpen).toBe(true);
  });

  it("tells the operator to start IPMIDeck again when it cannot restart itself", async () => {
    const user = userEvent.setup();
    withState({ upgrade: { ...automatic, restart: "manual" } });
    useUpdateInstallStore.setState({
      snapshot: { phase: "restarting", target: "2.1.0", restart: "manual" },
    });
    openDialog();
    await waitFor(() => expect(screen.getByText(/updateDialog\.stopped/)).toBeTruthy());
    // Nothing more happens here until it is started again, so the dialog may be put away.
    await user.keyboard("{Escape}");
    await waitFor(() => expect(useUIOverlayStore.getState().updateOpen).toBe(false));
  });

  it("counts as an open overlay so page shortcuts do not fire underneath it", () => {
    useUIOverlayStore.getState().setUpdateOpen(true);
    expect(useUIOverlayStore.getState().anyOverlayOpen()).toBe(true);
  });
});

describe("the new-version toast", () => {
  it("announces a newer version once, with the way into the dialog", () => {
    withState({});
    const { unmount } = render(<UpdateNotifier />);
    expect(toast).toHaveBeenCalledTimes(1);
    const [, options] = (toast as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    options.action.onClick();
    expect(useUIOverlayStore.getState().updateOpen).toBe(true);
    expect(localStorage.getItem(UPDATE_TOAST_KEY)).toBe("2.1.0");

    unmount();
    render(<UpdateNotifier />);
    expect(toast).toHaveBeenCalledTimes(1);
  });

  it("uses the warning toast for a security release", () => {
    withState({ is_security: true });
    render(<UpdateNotifier />);
    expect(toast.warning).toHaveBeenCalledTimes(1);
    expect(toast).not.toHaveBeenCalled();
  });

  it("says nothing while the instance is current", () => {
    withState({ update_available: false, upgrade: null });
    render(<UpdateNotifier />);
    expect(toast).not.toHaveBeenCalled();
    expect(toast.warning).not.toHaveBeenCalled();
  });
});
