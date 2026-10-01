import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

/**
 * The one question the setup wizard asks about the network.
 *
 * It has to be pre-ticked (the operator is offered the choice, not made to hunt for it), it has
 * to record the answer, and — critically — a failure to record it must not strand someone on
 * this step. That last property is what this file is really guarding.
 */

vi.mock("@/api/client", () => ({
  get: vi.fn(() => Promise.resolve({ servers: [] })),
  post: vi.fn(() => Promise.resolve({ success: true })),
  put: vi.fn(() => Promise.resolve({ success: true })),
  del: vi.fn(() => Promise.resolve({ success: true })),
  setUnauthorizedHandler: vi.fn(),
  api: vi.fn(() => Promise.resolve({})),
}));

vi.mock("sonner", () => ({
  toast: { warning: vi.fn(), error: vi.fn(), success: vi.fn(), info: vi.fn() },
}));

import { put } from "@/api/client";
import { toast } from "sonner";
import SetupPage from "@/pages/SetupPage";

function renderWizardAtAuthStep() {
  const view = render(
    <MemoryRouter>
      <SetupPage />
    </MemoryRouter>,
  );
  // Step 0 is the welcome screen; the question lives on the step after it.
  return view;
}

async function goToAuthStep(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /setup\.getStarted|get started/i }));
}

function checkbox(): HTMLInputElement {
  return document.getElementById("setup-update-checks") as HTMLInputElement;
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

describe("the setup wizard's update question", () => {
  it("is asked on the existing step, not on a step of its own", async () => {
    const user = userEvent.setup();
    renderWizardAtAuthStep();
    await goToAuthStep(user);
    // The same screen still carries the account decision — no extra step was inserted.
    expect(screen.getByText(/Protect the dashboard/i)).toBeTruthy();
    expect(checkbox()).toBeTruthy();
  });

  it("is pre-ticked", async () => {
    const user = userEvent.setup();
    renderWizardAtAuthStep();
    await goToAuthStep(user);
    expect(checkbox().checked).toBe(true);
  });

  it("has a label that toggles it, so it is operable without a pointer", async () => {
    const user = userEvent.setup();
    renderWizardAtAuthStep();
    await goToAuthStep(user);
    const box = checkbox();
    await user.click(screen.getByLabelText(/setup\.auth\.updateChecksLabel|check for new/i));
    expect(box.checked).toBe(false);
  });

  it("records the answer once the account decision goes through", async () => {
    const user = userEvent.setup();
    renderWizardAtAuthStep();
    await goToAuthStep(user);
    await user.click(screen.getByText(/setup\.auth\.noTitle|open access/i));
    await user.click(screen.getByRole("button", { name: /common\.continue|continue/i }));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/updates/consent", { enabled: true }),
    );
  });

  it("records a declined answer as declined", async () => {
    const user = userEvent.setup();
    renderWizardAtAuthStep();
    await goToAuthStep(user);
    await user.click(screen.getByLabelText(/setup\.auth\.updateChecksLabel|check for new/i));
    await user.click(screen.getByText(/setup\.auth\.noTitle|open access/i));
    await user.click(screen.getByRole("button", { name: /common\.continue|continue/i }));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/updates/consent", { enabled: false }),
    );
  });

  it("does not strand the operator when the preference cannot be saved", async () => {
    (put as unknown as { mockRejectedValueOnce: (e: Error) => void }).mockRejectedValueOnce(
      new Error("write failed"),
    );
    const user = userEvent.setup();
    renderWizardAtAuthStep();
    await goToAuthStep(user);
    await user.click(screen.getByText(/setup\.auth\.noTitle|open access/i));
    await user.click(screen.getByRole("button", { name: /common\.continue|continue/i }));
    // The wizard moved on to the add-server step regardless: the vendor selector only exists
    // on that step.
    await waitFor(() => expect(screen.getByRole("combobox")).toBeTruthy());
  });

  async function answerAndContinue(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByText(/setup\.auth\.noTitle|open access/i));
    await user.click(screen.getByRole("button", { name: /common\.continue|continue/i }));
  }

  it("tells the operator when the answer could not be saved", async () => {
    // Nothing is stored in that case, so no unattended check will run whatever the box showed.
    (put as unknown as { mockRejectedValueOnce: (e: Error) => void }).mockRejectedValueOnce(
      new Error("API error: 500 Internal Server Error"),
    );
    const user = userEvent.setup();
    renderWizardAtAuthStep();
    await goToAuthStep(user);
    await answerAndContinue(user);
    await waitFor(() => expect(toast.warning).toHaveBeenCalledTimes(1));
  });

  it("says nothing when update checks are switched off in the configuration", async () => {
    // The route does not exist then, and there is nothing to record.
    (put as unknown as { mockRejectedValueOnce: (e: Error) => void }).mockRejectedValueOnce(
      new Error("API error: 404 Not Found"),
    );
    const user = userEvent.setup();
    renderWizardAtAuthStep();
    await goToAuthStep(user);
    await answerAndContinue(user);
    await waitFor(() => expect(screen.getByRole("combobox")).toBeTruthy());
    expect(toast.warning).not.toHaveBeenCalled();
  });
});
