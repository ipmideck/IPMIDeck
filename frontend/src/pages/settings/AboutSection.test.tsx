import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

/**
 * What the Check now button reports.
 *
 * A failed check still carries the update an earlier check found, and that answer is still true:
 * hiding it behind "the check could not be completed" would tell the operator less than the
 * server knows.
 */

const baseState = {
  success: true,
  enabled: true,
  consent: true,
  current_version: "2.0.1",
  latest_version: null as string | null,
  update_available: false,
  is_security: false,
  release_url: "https://example.invalid/releases",
  install_method: "pip",
  checked_at: null,
  error: null as string | null,
};

vi.mock("@/api/client", () => ({
  get: vi.fn(() => Promise.resolve({ ...baseState })),
  post: vi.fn(() => Promise.resolve({ ...baseState })),
  put: vi.fn(() => Promise.resolve({ success: true })),
  del: vi.fn(() => Promise.resolve({ success: true })),
  setUnauthorizedHandler: vi.fn(),
  api: vi.fn(() => Promise.resolve({})),
}));

vi.mock("@/pages/settings/SettingsContext", () => ({
  useSettings: () => ({ appVersion: "2.0.1", online: true, offlineTip: "" }),
}));

import { post } from "@/api/client";
import { AboutSection } from "@/pages/settings/AboutSection";
import { useUpdateStore } from "@/stores/update-store";

function answerCheckWith(body: Partial<typeof baseState>) {
  (post as unknown as { mockResolvedValueOnce: (v: unknown) => void }).mockResolvedValueOnce({
    ...baseState,
    ...body,
  });
}

async function pressCheck() {
  const user = userEvent.setup();
  render(<AboutSection headingRef={null} />);
  await user.click(await screen.findByRole("button", { name: /updates\.checkNow|check now/i }));
}

beforeEach(() => {
  vi.clearAllMocks();
  useUpdateStore.setState({ state: { ...baseState }, checking: false });
});

afterEach(() => {
  cleanup();
});

describe("the Check now outcome", () => {
  it("keeps showing an update found earlier when this check fails", async () => {
    answerCheckWith({
      success: false,
      error: "rate_limited",
      update_available: true,
      latest_version: "99.0.0",
    });
    await pressCheck();
    expect(await screen.findByText(/updates\.updateAvailable|99\.0\.0/)).toBeTruthy();
    expect(screen.queryByText(/updates\.checkFailed|could not be completed/i)).toBeNull();
  });

  it("reports a failure when nothing is known", async () => {
    answerCheckWith({ success: false, error: "not_checked" });
    await pressCheck();
    expect(await screen.findByText(/updates\.checkFailed|could not be completed/i)).toBeTruthy();
  });

  it("reports up to date only after a clean check", async () => {
    answerCheckWith({});
    await pressCheck();
    expect(await screen.findByText(/updates\.upToDate|is the latest/)).toBeTruthy();
    expect(
      screen.queryByText(/updates\.(update|securityUpdate)Available|is available/),
    ).toBeNull();
    expect(screen.queryByText(/updates\.checkFailed|could not be completed/i)).toBeNull();
  });
});
