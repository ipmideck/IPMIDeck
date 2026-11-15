import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

/**
 * The date and time settings: what the group offers, that a choice is saved on the server as
 * one JSON value, and that a refused save is reported and leaves the previous choice in place.
 */

vi.mock("@/api/client", () => ({
  get: vi.fn(() => Promise.resolve({ success: true, value: null })),
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

import "@/i18n";
import { put } from "@/api/client";
import { toast } from "sonner";
import { DEFAULT_DISPLAY_PREFS } from "@/lib/datetime";
import { AppearanceSection } from "@/pages/settings/AppearanceSection";
import { useDisplayPrefsStore } from "@/stores/display-prefs-store";

const URL = "/api/system/app-config/display.datetime";

function renderSection() {
  return render(<AppearanceSection headingRef={null} />);
}

beforeEach(() => {
  vi.clearAllMocks();
  useDisplayPrefsStore.setState({ prefs: { ...DEFAULT_DISPLAY_PREFS }, hydrated: true });
});

afterEach(() => {
  cleanup();
});

describe("Date and time settings", () => {
  it("offers time zone, clock, seconds and date format, with a preview", () => {
    renderSection();
    expect(screen.getByRole("heading", { name: /date and time/i })).toBeInTheDocument();

    const zone = screen.getByLabelText(/time zone/i) as HTMLSelectElement;
    expect(zone.value).toBe("browser");
    expect(zone.options[0].value).toBe("browser");
    expect(zone.options[0].textContent).toMatch(/this browser/i);
    expect([...zone.options].map((o) => o.value)).toContain("UTC");

    const clock = screen.getByLabelText(/^clock$/i) as HTMLSelectElement;
    expect([...clock.options].map((o) => o.value)).toEqual(["auto", "24h", "12h"]);
    const seconds = screen.getByLabelText(/^seconds$/i) as HTMLSelectElement;
    expect([...seconds.options].map((o) => o.value)).toEqual(["auto", "show", "hide"]);
    const date = screen.getByLabelText(/date format/i) as HTMLSelectElement;
    expect([...date.options].map((o) => o.value)).toEqual(["language", "iso"]);
    expect(date.options[1].textContent).toMatch(/\d{4}-\d{2}-\d{2}/);

    expect(screen.getByText(/^now:/i)).toBeInTheDocument();
  });

  it("saves a 24-hour clock as one JSON value", async () => {
    const user = userEvent.setup();
    renderSection();
    await user.selectOptions(screen.getByLabelText(/^clock$/i), "24h");

    expect(put).toHaveBeenCalledTimes(1);
    const [url, body] = vi.mocked(put).mock.calls[0] as [string, { value: string }];
    expect(url).toBe(URL);
    expect(JSON.parse(body.value)).toEqual({ ...DEFAULT_DISPLAY_PREFS, timeFormat: "24h" });
    expect((screen.getByLabelText(/^clock$/i) as HTMLSelectElement).value).toBe("24h");
  });

  it("reports a refused save and returns to the previous choice", async () => {
    vi.mocked(put).mockResolvedValueOnce({ success: false, error: "invalid_value" });
    const user = userEvent.setup();
    renderSection();
    const clock = screen.getByLabelText(/^clock$/i) as HTMLSelectElement;
    await user.selectOptions(clock, "24h");

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringMatching(/settings\.datetime\.saveFailed|could not save the date and time/i),
      ),
    );
    expect(clock.value).toBe("auto");
    expect(useDisplayPrefsStore.getState().prefs).toEqual(DEFAULT_DISPLAY_PREFS);
  });
});
