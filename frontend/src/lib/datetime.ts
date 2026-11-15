/**
 * Shared date and time formatting.
 *
 * Every timestamp in the interface goes through these functions, so one display preference
 * (time zone, clock, seconds, date format) applies everywhere. The defaults reproduce the
 * formats each screen used before the preference existed: the interface language's locale,
 * the browser's time zone, and each call site's own seconds and clock.
 *
 * Parsing lives here too. The server stores SQLite timestamps in UTC without an offset
 * ("2026-10-14 12:00:00"), which a browser would read as local time; toInstant reads them as UTC.
 *
 * Pure module: no store, no i18n. The hook in stores/display-prefs-store.ts binds it to both.
 */

export type TimeFormatPref = "auto" | "24h" | "12h";
export type SecondsPref = "auto" | "show" | "hide";
export type DateFormatPref = "language" | "iso";

export interface DisplayPrefs {
  /** "browser" or an IANA zone name. */
  timeZone: string;
  timeFormat: TimeFormatPref;
  seconds: SecondsPref;
  dateFormat: DateFormatPref;
}

export const DEFAULT_DISPLAY_PREFS: DisplayPrefs = {
  timeZone: "browser",
  timeFormat: "auto",
  seconds: "auto",
  dateFormat: "language",
};

/** A call site's own historical format, used while a preference is left on "auto". */
export interface SiteStyle {
  seconds: boolean;
  /** The site always showed a 24-hour clock, whatever the language. */
  clock24?: boolean;
}

export interface FormatContext {
  /** Intl locale tag; undefined means the runtime default locale. */
  locale?: string;
  prefs?: DisplayPrefs;
}

const TIME_FORMATS: readonly TimeFormatPref[] = ["auto", "24h", "12h"];
const SECONDS: readonly SecondsPref[] = ["auto", "show", "hide"];
const DATE_FORMATS: readonly DateFormatPref[] = ["language", "iso"];
const ZONE_SHAPE = /^[A-Za-z0-9_+\-/]{1,64}$/;

/* --- Parsing --- */

const DATE_TIME_PREFIX = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/;
const OFFSET_SUFFIX = /(?:Z|[+-]\d{2}:?\d{2})$/i;

/** Turn an API timestamp into a Date. Offset-less date-times are UTC. Invalid input -> null. */
export function toInstant(value: string | number | Date | null | undefined): Date | null {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  if (typeof value === "number") return Number.isFinite(value) ? new Date(value) : null;
  if (typeof value !== "string") return null;
  let s = value.trim();
  if (!s) return null;
  s = s.replace(/(\.\d{3})\d+/, "$1");
  if (DATE_TIME_PREFIX.test(s) && !OFFSET_SUFFIX.test(s)) {
    s = s.replace(" ", "T") + "Z";
  }
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

/* --- Preferences --- */

function pick<T extends string>(raw: unknown, allowed: readonly T[], fallback: T): T {
  return typeof raw === "string" && (allowed as readonly string[]).includes(raw)
    ? (raw as T)
    : fallback;
}

/** Read a stored preference (object or JSON string). Each bad field falls back; never throws. */
export function sanitizeDisplayPrefs(raw: unknown): DisplayPrefs {
  let obj: unknown = raw;
  if (typeof raw === "string") {
    try {
      obj = JSON.parse(raw);
    } catch {
      obj = null;
    }
  }
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return { ...DEFAULT_DISPLAY_PREFS };
  const o = obj as Record<string, unknown>;
  const d = DEFAULT_DISPLAY_PREFS;
  return {
    timeZone:
      typeof o.timeZone === "string" && ZONE_SHAPE.test(o.timeZone) ? o.timeZone : d.timeZone,
    timeFormat: pick(o.timeFormat, TIME_FORMATS, d.timeFormat),
    seconds: pick(o.seconds, SECONDS, d.seconds),
    dateFormat: pick(o.dateFormat, DATE_FORMATS, d.dateFormat),
  };
}

const zoneValidity = new Map<string, boolean>();

/** The zone to hand to Intl: undefined for "browser" or a zone this browser does not know. */
export function resolveTimeZone(timeZone: string): string | undefined {
  if (!timeZone || timeZone === "browser") return undefined;
  let ok = zoneValidity.get(timeZone);
  if (ok === undefined) {
    try {
      new Intl.DateTimeFormat("en-US", { timeZone });
      ok = true;
    } catch {
      ok = false;
    }
    zoneValidity.set(timeZone, ok);
  }
  return ok ? timeZone : undefined;
}

/** The name of the zone actually used, e.g. "Europe/Rome" when the preference is "browser". */
export function activeTimeZone(prefs: DisplayPrefs = DEFAULT_DISPLAY_PREFS): string {
  const timeZone = resolveTimeZone(prefs.timeZone);
  return getFormatter(undefined, timeZone ? { timeZone } : {}).resolvedOptions().timeZone;
}

/** Zones for a picker: the browser's list plus UTC and the saved zone, sorted, no duplicates. */
export function listTimeZones(saved?: string): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
  let zones: string[] = [];
  if (typeof intl.supportedValuesOf === "function") {
    try {
      zones = intl.supportedValuesOf("timeZone");
    } catch {
      zones = [];
    }
  }
  if (zones.length === 0) zones = [activeTimeZone()];
  const all = new Set(zones);
  all.add("UTC");
  if (saved && saved !== "browser") all.add(saved);
  return [...all].sort();
}

/* --- Formatting --- */

/** What a formatter shows for a value it cannot read: the value itself, or nothing. */
function unparsed(value: unknown): string {
  return value == null ? "" : String(value);
}

const formatters = new Map<string, Intl.DateTimeFormat>();

function getFormatter(locale: string | undefined, options: Intl.DateTimeFormatOptions) {
  const key = JSON.stringify([locale ?? null, options]);
  let f = formatters.get(key);
  if (!f) {
    try {
      f = new Intl.DateTimeFormat(locale, options);
    } catch {
      const { timeZone: _ignored, ...rest } = options;
      f = new Intl.DateTimeFormat(locale, rest);
    }
    formatters.set(key, f);
  }
  return f;
}

type HourCycle = "h23" | "h12";

function hourCycleFor(prefs: DisplayPrefs, site: SiteStyle): HourCycle | undefined {
  if (prefs.timeFormat === "24h") return "h23";
  if (prefs.timeFormat === "12h") return "h12";
  return site.clock24 ? "h23" : undefined;
}

function showSeconds(prefs: DisplayPrefs, site: SiteStyle): boolean {
  return prefs.seconds === "show" || (prefs.seconds === "auto" && site.seconds);
}

function zoneOption(prefs: DisplayPrefs): { timeZone?: string } {
  const timeZone = resolveTimeZone(prefs.timeZone);
  return timeZone ? { timeZone } : {};
}

function timeOptions(prefs: DisplayPrefs, site: SiteStyle): Intl.DateTimeFormatOptions {
  const hourCycle = hourCycleFor(prefs, site);
  return {
    hour: hourCycle === "h23" ? "2-digit" : "numeric",
    minute: "2-digit",
    ...(showSeconds(prefs, site) ? { second: "2-digit" as const } : {}),
    ...(hourCycle ? { hourCycle } : {}),
    ...zoneOption(prefs),
  };
}

function isoDate(d: Date, prefs: DisplayPrefs): string {
  const parts = getFormatter("en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    numberingSystem: "latn",
    calendar: "gregory",
    ...zoneOption(prefs),
  }).formatToParts(d);
  const part = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${part("year").padStart(4, "0")}-${part("month")}-${part("day")}`;
}

/** A time of day, e.g. "14:05:09" or "2:05 PM". */
export function formatTime(
  value: string | number | Date,
  ctx: FormatContext,
  site: SiteStyle,
): string {
  const d = toInstant(value);
  if (!d) return unparsed(value);
  const prefs = ctx.prefs ?? DEFAULT_DISPLAY_PREFS;
  return getFormatter(ctx.locale, timeOptions(prefs, site)).format(d);
}

/** A calendar date in the language's form, or YYYY-MM-DD. */
export function formatDate(value: string | number | Date, ctx: FormatContext): string {
  const d = toInstant(value);
  if (!d) return unparsed(value);
  const prefs = ctx.prefs ?? DEFAULT_DISPLAY_PREFS;
  if (prefs.dateFormat === "iso") return isoDate(d, prefs);
  return getFormatter(ctx.locale, {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    ...zoneOption(prefs),
  }).format(d);
}

/** A date and a time. With default preferences this matches the browser's toLocaleString. */
export function formatDateTime(
  value: string | number | Date,
  ctx: FormatContext,
  site: SiteStyle,
): string {
  const d = toInstant(value);
  if (!d) return unparsed(value);
  const prefs = ctx.prefs ?? DEFAULT_DISPLAY_PREFS;
  if (prefs.dateFormat === "iso") {
    return `${isoDate(d, prefs)} ${formatTime(d, ctx, site)}`;
  }
  const hourCycle = hourCycleFor(prefs, site);
  return getFormatter(ctx.locale, {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: hourCycle === "h23" ? "2-digit" : "numeric",
    minute: "numeric",
    ...(showSeconds(prefs, site) ? { second: "numeric" as const } : {}),
    ...(hourCycle ? { hourCycle } : {}),
    ...zoneOption(prefs),
  }).format(d);
}
