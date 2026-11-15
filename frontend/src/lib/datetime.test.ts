import { describe, expect, it } from "vitest";
import {
  DEFAULT_DISPLAY_PREFS,
  activeTimeZone,
  formatDate,
  formatDateTime,
  formatTime,
  listTimeZones,
  resolveTimeZone,
  sanitizeDisplayPrefs,
  toInstant,
  type DisplayPrefs,
} from "@/lib/datetime";

const prefs = (p: Partial<DisplayPrefs>): DisplayPrefs => ({ ...DEFAULT_DISPLAY_PREFS, ...p });

describe("toInstant", () => {
  const noon = Date.UTC(2026, 9, 14, 12);

  it("reads offset-less server timestamps as UTC", () => {
    expect(toInstant("2026-10-14 12:00:00")?.getTime()).toBe(noon);
    expect(toInstant("2026-10-14T12:00:00")?.getTime()).toBe(noon);
    expect(toInstant(" 2026-10-14 12:00:00 ")?.getTime()).toBe(noon);
  });

  it("respects an explicit offset or Z", () => {
    expect(toInstant("2026-10-14T12:00:00+02:00")?.getTime()).toBe(Date.UTC(2026, 9, 14, 10));
    expect(toInstant("2026-10-14T12:00:00Z")?.getTime()).toBe(noon);
  });

  it("keeps milliseconds from microsecond timestamps", () => {
    expect(toInstant("2026-10-14T12:00:00.123456+00:00")?.getTime()).toBe(noon + 123);
    expect(toInstant("2026-10-14 12:00:00.123456")?.getTime()).toBe(noon + 123);
  });

  it("passes numbers and dates through and rejects garbage", () => {
    expect(toInstant(noon)?.getTime()).toBe(noon);
    expect(toInstant(new Date(noon))?.getTime()).toBe(noon);
    expect(toInstant("not a date")).toBeNull();
    expect(toInstant("")).toBeNull();
    expect(toInstant(Number.NaN)).toBeNull();
    expect(toInstant(new Date("x"))).toBeNull();
  });
});

describe("defaults reproduce the formats used before the preference existed", () => {
  const d = new Date(Date.UTC(2026, 9, 14, 13, 7, 9));

  it.each(["en-US", "de", "ja"])("formatDateTime matches toLocaleString for %s", (locale) => {
    expect(formatDateTime(d, { locale }, { seconds: true })).toBe(d.toLocaleString(locale));
  });

  it("formatDateTime with no locale matches toLocaleString()", () => {
    expect(formatDateTime(d, { locale: undefined }, { seconds: true })).toBe(d.toLocaleString());
  });

  it.each(["en-US", "de", "ja", "ko"])("forced 24-hour time matches the old call for %s", (locale) => {
    const legacy = d.toLocaleTimeString(locale, {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    expect(formatTime(d, { locale }, { seconds: true, clock24: true })).toBe(legacy);
    const legacyShort = d.toLocaleTimeString(locale, {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
    });
    expect(formatTime(d, { locale }, { seconds: false, clock24: true })).toBe(legacyShort);
  });

  it("output is unparseable input echoed back", () => {
    expect(formatDateTime("garbage", { locale: "en-US" }, { seconds: true })).toBe("garbage");
    expect(formatTime("garbage", { locale: "en-US" }, { seconds: true })).toBe("garbage");
    expect(formatDate("garbage", { locale: "en-US" })).toBe("garbage");
  });
});

describe("preferences", () => {
  const ny24 = prefs({ timeZone: "America/New_York", timeFormat: "24h", seconds: "hide" });

  it("converts to the chosen zone, following daylight saving time", () => {
    const ctx = { locale: "en-US", prefs: ny24 };
    expect(formatTime(Date.UTC(2026, 0, 15, 12), ctx, { seconds: true })).toBe("07:00");
    expect(formatTime(Date.UTC(2026, 6, 15, 12), ctx, { seconds: true })).toBe("08:00");
  });

  it("builds ISO dates in the chosen zone", () => {
    const ctx = { locale: "de", prefs: { ...ny24, dateFormat: "iso" as const } };
    const instant = Date.UTC(2026, 6, 4, 3, 30);
    expect(formatDateTime(instant, ctx, { seconds: true })).toBe("2026-07-03 23:30");
    expect(formatDate(instant, ctx)).toBe("2026-07-03");
  });

  it("ISO dates stay Latin digits in every language", () => {
    const ctx = { locale: "ar-EG", prefs: prefs({ timeZone: "UTC", dateFormat: "iso" }) };
    expect(formatDate(Date.UTC(2026, 0, 2, 12), ctx)).toBe("2026-01-02");
  });

  it("shows midnight as 00, never 24", () => {
    const ctx = { locale: "en-US", prefs: prefs({ timeZone: "UTC", timeFormat: "24h" }) };
    const out = formatTime(Date.UTC(2026, 0, 1, 0, 5), ctx, { seconds: false });
    expect(out).toContain("00:05");
    expect(out).not.toContain("24:05");
    const forced = formatTime(
      Date.UTC(2026, 0, 1, 0, 5),
      { locale: "en-US", prefs: prefs({ timeZone: "UTC" }) },
      { seconds: false, clock24: true },
    );
    expect(forced).toBe("00:05");
  });

  it("12-hour clock overrides a 24-hour site and language", () => {
    const ctx = { locale: "en-US", prefs: prefs({ timeZone: "UTC", timeFormat: "12h" }) };
    expect(formatTime(Date.UTC(2026, 0, 1, 14, 5), ctx, { seconds: false, clock24: true })).toMatch(
      /2:05\s?PM/u,
    );
  });

  it("seconds can be forced on or off", () => {
    const base = { timeZone: "UTC", timeFormat: "24h" as const };
    const t = Date.UTC(2026, 0, 1, 14, 5, 9);
    expect(formatTime(t, { locale: "en-US", prefs: prefs({ ...base, seconds: "show" }) }, { seconds: false })).toBe("14:05:09");
    expect(formatTime(t, { locale: "en-US", prefs: prefs({ ...base, seconds: "hide" }) }, { seconds: true })).toBe("14:05");
  });

  it("an unknown zone falls back to the browser zone without throwing", () => {
    const d = Date.UTC(2026, 9, 14, 13, 7, 9);
    const bad = { locale: "en-US", prefs: prefs({ timeZone: "Mars/Olympus" }) };
    const browser = { locale: "en-US", prefs: DEFAULT_DISPLAY_PREFS };
    expect(formatDateTime(d, bad, { seconds: true })).toBe(formatDateTime(d, browser, { seconds: true }));
    expect(resolveTimeZone("Mars/Olympus")).toBeUndefined();
    expect(resolveTimeZone("browser")).toBeUndefined();
    expect(resolveTimeZone("UTC")).toBe("UTC");
    expect(activeTimeZone(prefs({ timeZone: "Mars/Olympus" }))).toBe(activeTimeZone());
    expect(activeTimeZone(prefs({ timeZone: "Asia/Tokyo" }))).toBe("Asia/Tokyo");
  });
});

describe("sanitizeDisplayPrefs", () => {
  it("parses a stored JSON string", () => {
    const stored = JSON.stringify({ dateFormat: "iso", seconds: "hide", timeFormat: "24h", timeZone: "UTC" });
    expect(sanitizeDisplayPrefs(stored)).toEqual({
      timeZone: "UTC",
      timeFormat: "24h",
      seconds: "hide",
      dateFormat: "iso",
    });
  });

  it("falls back per field", () => {
    expect(
      sanitizeDisplayPrefs({ timeZone: "a b", timeFormat: "24h", seconds: true, dateFormat: "dmy" }),
    ).toEqual({ ...DEFAULT_DISPLAY_PREFS, timeFormat: "24h" });
  });

  it("returns defaults for anything unreadable", () => {
    for (const raw of [null, undefined, "not json", "[]", 5, JSON.stringify("browser")]) {
      expect(sanitizeDisplayPrefs(raw)).toEqual(DEFAULT_DISPLAY_PREFS);
    }
  });
});

describe("listTimeZones", () => {
  it("always contains UTC, sorted and without duplicates", () => {
    const zones = listTimeZones("browser");
    expect(zones).toContain("UTC");
    expect(zones).not.toContain("browser");
    expect([...zones].sort()).toEqual(zones);
    expect(new Set(zones).size).toBe(zones.length);
  });

  it("includes the saved zone even when the browser does not list it", () => {
    expect(listTimeZones("Asia/Kolkata")).toContain("Asia/Kolkata");
    expect(listTimeZones("Etc/GMT+5")).toContain("Etc/GMT+5");
  });
});
