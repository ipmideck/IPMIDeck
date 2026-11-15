import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

vi.mock("@/api/client", () => ({
  get: vi.fn(() => Promise.resolve({ success: true, value: null })),
  post: vi.fn(() => Promise.resolve({ success: true })),
  put: vi.fn(() => Promise.resolve({ success: true })),
  del: vi.fn(() => Promise.resolve({ success: true })),
  setUnauthorizedHandler: vi.fn(),
  api: vi.fn(() => Promise.resolve({})),
}));

import i18n from "@/i18n";
import { get, put } from "@/api/client";
import { DEFAULT_DISPLAY_PREFS, type DisplayPrefs } from "@/lib/datetime";
import { useDateTimeFormat, useDisplayPrefsStore } from "@/stores/display-prefs-store";

const URL = "/api/system/app-config/display.datetime";
const NY: DisplayPrefs = {
  timeZone: "America/New_York",
  timeFormat: "24h",
  seconds: "hide",
  dateFormat: "iso",
};

function reset() {
  useDisplayPrefsStore.setState({ prefs: { ...DEFAULT_DISPLAY_PREFS }, hydrated: false });
}

beforeEach(() => {
  reset();
  vi.mocked(get).mockReset();
  vi.mocked(put).mockReset();
  vi.mocked(get).mockResolvedValue({ success: true, value: null });
  vi.mocked(put).mockResolvedValue({ success: true });
});

afterEach(reset);

describe("useDisplayPrefsStore", () => {
  it("keeps defaults when nothing is stored, and writes nothing back", async () => {
    await useDisplayPrefsStore.getState().hydrate();
    expect(get).toHaveBeenCalledWith(URL);
    expect(useDisplayPrefsStore.getState().prefs).toEqual(DEFAULT_DISPLAY_PREFS);
    expect(useDisplayPrefsStore.getState().hydrated).toBe(true);
    expect(put).not.toHaveBeenCalled();
  });

  it("applies a stored JSON string", async () => {
    vi.mocked(get).mockResolvedValue({ success: true, value: JSON.stringify(NY) });
    await useDisplayPrefsStore.getState().hydrate();
    expect(useDisplayPrefsStore.getState().prefs).toEqual(NY);
  });

  it("hydrates only once", async () => {
    await useDisplayPrefsStore.getState().hydrate();
    await useDisplayPrefsStore.getState().hydrate();
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("keeps defaults when the read fails", async () => {
    vi.mocked(get).mockRejectedValue(new Error("offline"));
    await useDisplayPrefsStore.getState().hydrate();
    expect(useDisplayPrefsStore.getState().prefs).toEqual(DEFAULT_DISPLAY_PREFS);
    expect(useDisplayPrefsStore.getState().hydrated).toBe(true);
  });

  it("saves the whole preference as one JSON string", async () => {
    await useDisplayPrefsStore.getState().setPrefs(NY);
    expect(put).toHaveBeenCalledWith(URL, { value: JSON.stringify(NY) });
    expect(useDisplayPrefsStore.getState().prefs).toEqual(NY);
  });

  it("reverts and rejects when the server refuses the value", async () => {
    vi.mocked(put).mockResolvedValue({ success: false, error: "invalid_value" });
    await expect(useDisplayPrefsStore.getState().setPrefs(NY)).rejects.toThrow();
    expect(useDisplayPrefsStore.getState().prefs).toEqual(DEFAULT_DISPLAY_PREFS);
  });

  it("reverts and rejects when the request fails", async () => {
    vi.mocked(put).mockRejectedValue(new Error("offline"));
    await expect(useDisplayPrefsStore.getState().setPrefs(NY)).rejects.toThrow("offline");
    expect(useDisplayPrefsStore.getState().prefs).toEqual(DEFAULT_DISPLAY_PREFS);
  });
});

describe("useDateTimeFormat", () => {
  const instant = Date.UTC(2026, 6, 15, 12, 4, 5);

  afterEach(async () => {
    await act(async () => {
      await i18n.changeLanguage("en");
    });
  });

  it("re-formats when the preference changes, without remounting", async () => {
    await act(async () => {
      await i18n.changeLanguage("en");
    });
    const { result } = renderHook(() => useDateTimeFormat());
    const site = { seconds: false };
    const before = result.current.formatTime(instant, site);

    await act(async () => {
      await useDisplayPrefsStore
        .getState()
        .setPrefs({ ...DEFAULT_DISPLAY_PREFS, timeZone: "America/New_York", timeFormat: "24h" });
    });
    expect(result.current.formatTime(instant, site)).toBe("08:04");
    expect(result.current.timeZone).toBe("America/New_York");

    await act(async () => {
      await useDisplayPrefsStore
        .getState()
        .setPrefs({ ...DEFAULT_DISPLAY_PREFS, timeZone: "UTC", timeFormat: "12h" });
    });
    expect(result.current.formatTime(instant, site)).toMatch(/^12:04\s?PM$/u);
    expect(before).toBe(new Date(instant).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }));
  });

  it("follows the interface language", async () => {
    await act(async () => {
      await i18n.changeLanguage("en");
    });
    const { result } = renderHook(() => useDateTimeFormat());
    const site = { seconds: true };
    expect(result.current.formatDateTime(instant, site)).toBe(new Date(instant).toLocaleString("en-US"));

    await act(async () => {
      await i18n.changeLanguage("de");
    });
    expect(i18n.resolvedLanguage).toBe("de");
    expect(result.current.formatDateTime(instant, site)).toBe(new Date(instant).toLocaleString("de"));
  });

  it("browserLocale uses the runtime default locale whatever the language", async () => {
    await act(async () => {
      await i18n.changeLanguage("ja");
    });
    const { result } = renderHook(() => useDateTimeFormat({ browserLocale: true }));
    expect(result.current.formatDateTime(instant, { seconds: true })).toBe(
      new Date(instant).toLocaleString(),
    );
  });
});
