import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

/**
 * SEC-05 (D2) — executable proof for the ONE new UI field this phase adds.
 *
 * The maintainer approved exactly one exception to "no new UI complexity": a
 * `Current password` input inside the Security section's EXISTING enable-auth
 * form. This file proves it works AND, just as importantly, that it does NOT
 * break the account-less enable path — the case where the backend correctly
 * demands no current password and an unconditional guard would lock the
 * operator out of a form they must be able to submit.
 *
 * A component test rather than a browser pass: the SPA redirects to /setup
 * until a server exists, and vitest is already step 4 of the CI gate whereas
 * Playwright lives outside the repo and outside CI.
 */

vi.mock("@/api/client", () => ({
  get: vi.fn(() => Promise.resolve({})),
  post: vi.fn(() => Promise.resolve({ success: true })),
  put: vi.fn(() => Promise.resolve({ success: true })),
  del: vi.fn(() => Promise.resolve({ success: true })),
  setUnauthorizedHandler: vi.fn(),
  api: vi.fn(() => Promise.resolve({})),
}));

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
}));

import { post } from "@/api/client";
import { toast } from "sonner";
import { useAuthStore } from "@/stores/auth-store";
import { SecuritySection } from "@/pages/settings/SecuritySection";
import { SettingsContext, type SettingsCtx } from "@/pages/settings/SettingsContext";

const ctx: SettingsCtx = {
  online: true,
  offlineTip: undefined,
  certPath: "",
  setCertPath: () => {},
  keyPath: "",
  setKeyPath: () => {},
  appVersion: null,
};

/** Renders the enable-auth branch (authEnabled=false) for the given account state. */
function renderSection(hasUser: boolean) {
  useAuthStore.setState({
    authEnabled: false,
    authenticated: false,
    hasUser,
    username: null,
  });
  return render(
    <SettingsContext.Provider value={ctx}>
      <SecuritySection headingRef={null} />
    </SettingsContext.Provider>
  );
}

/** The current-password input, identified by its placeholder i18n key. */
function currentPasswordInput(): HTMLElement | null {
  return screen.queryByPlaceholderText(/settings\.currentPasswordPlaceholder|current password/i);
}

/** The username input, identified by its placeholder i18n key. */
function usernameInput(): HTMLElement {
  return screen.getByPlaceholderText(/settings\.secUsernamePlaceholder|username/i);
}

/** The NEW-password input, identified by its placeholder i18n key. */
function newPasswordInput(): HTMLElement {
  return screen.getByPlaceholderText(/settings\.secPasswordPlaceholder|new password/i);
}

/** The confirm-new-password input, identified by its placeholder i18n key. */
function confirmPasswordInput(): HTMLElement {
  return screen.getByPlaceholderText(/settings\.secConfirmNewPasswordPlaceholder|confirm new password/i);
}

function enableButton(): HTMLElement {
  return screen.getByRole("button", { name: /settings\.enableAuth|enable/i });
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

describe("SecuritySection — the approved Current password field (SEC-05 / D2)", () => {
  it("renders the Current password input when an account already exists", () => {
    renderSection(true);
    expect(currentPasswordInput()).not.toBeNull();
  });

  it("blocks submission and toasts when an account exists and the field is empty", async () => {
    const user = userEvent.setup();
    renderSection(true);

    // Fields are addressed by placeholder, never by position: the form's field
    // ORDER is a UX decision that has already changed once, and a positional
    // lookup silently types into the wrong box when it does.
    await user.type(usernameInput(), "newadmin");
    await user.type(newPasswordInput(), "new-password-value");
    await user.type(confirmPasswordInput(), "new-password-value");
    // The Current password field is deliberately left empty.

    await user.click(enableButton());

    expect(toast.error).toHaveBeenCalled();
    expect(post).not.toHaveBeenCalled();
  });

  it("sends current_password when an account exists and the field is filled", async () => {
    const user = userEvent.setup();
    renderSection(true);

    await user.type(usernameInput(), "newadmin");
    await user.type(newPasswordInput(), "new-password-value");
    await user.type(confirmPasswordInput(), "new-password-value");
    await user.type(currentPasswordInput()!, "the-current-password");

    await user.click(enableButton());

    await waitFor(() => expect(post).toHaveBeenCalled());
    const [url, body] = vi.mocked(post).mock.calls[0] as [string, Record<string, unknown>];
    expect(url).toBe("/api/auth/configure");
    expect(body.current_password).toBe("the-current-password");
    expect(body.username).toBe("newadmin");
  });

  it("does NOT render the field, and does NOT block, when there is no account", async () => {
    const user = userEvent.setup();
    renderSection(false);

    // The single approved field must be absent — an account-less instance has no
    // current password, and demanding one would make enabling auth impossible.
    expect(currentPasswordInput()).toBeNull();

    // Only the two new-password fields exist here — no current password to ask for.
    expect(document.querySelectorAll('input[type="password"]').length).toBe(2);
    await user.type(usernameInput(), "firstadmin");
    await user.type(newPasswordInput(), "first-password-value");
    await user.type(confirmPasswordInput(), "first-password-value");

    await user.click(enableButton());

    await waitFor(() => expect(post).toHaveBeenCalled());
    const [url, body] = vi.mocked(post).mock.calls[0] as [string, Record<string, unknown>];
    expect(url).toBe("/api/auth/configure");
    expect(body).not.toHaveProperty("current_password");
  });
});
