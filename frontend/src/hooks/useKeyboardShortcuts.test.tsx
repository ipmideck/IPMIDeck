import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { useUIOverlayStore } from "@/stores/ui-overlay-store";

// vi.hoisted so the spy exists before the (hoisted) vi.mock factory runs.
// Targeted router mock ONLY — i18n/zustand are left real (RESEARCH Pitfall 5).
const navSpy = vi.hoisted(() => vi.fn());
vi.mock("react-router-dom", async (orig) => ({
  ...(await orig<typeof import("react-router-dom")>()),
  useNavigate: () => navSpy,
}));

function Harness() {
  useKeyboardShortcuts();
  return <input data-testid="field" aria-label="field" />;
}

function renderHarness() {
  return render(
    <MemoryRouter>
      <Harness />
    </MemoryRouter>
  );
}

beforeEach(() => {
  navSpy.mockClear();
  // Ensure no overlay is open so the overlay guard never masks the input-focus
  // guard under test.
  useUIOverlayStore.setState({ helpOpen: false, tourOpen: false, commandOpen: false });
});

afterEach(() => {
  cleanup();
});

describe("useKeyboardShortcuts input-focus guard (UX-01 / D-07)", () => {
  it("does NOT navigate when 'f' is typed while an input is focused", async () => {
    const user = userEvent.setup();
    renderHarness();

    const field = screen.getByTestId("field");
    await user.click(field);
    expect(field).toHaveFocus();

    // Typing "f" into the field must NOT trigger the /fanpilot page shortcut.
    await user.keyboard("f");
    expect(navSpy).not.toHaveBeenCalled();
  });

  it("DOES navigate to /fanpilot when 'f' is pressed and no input is focused", async () => {
    const user = userEvent.setup();
    renderHarness();

    // Blur any focused element so the keydown target is document.body, not an input.
    (document.activeElement as HTMLElement | null)?.blur();

    await user.keyboard("f");
    expect(navSpy).toHaveBeenCalledWith("/fanpilot");
  });
});
