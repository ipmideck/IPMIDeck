#!/usr/bin/env node
/**
 * Deep i18n parity gate (D-17).
 *
 * Loads frontend/src/i18n/locales/en/translation.json as the master and validates
 * every other catalog. Exits NON-ZERO on any failure (prints all failures first),
 * otherwise prints "i18n parity OK" and exits 0.
 *
 * Checks per catalog:
 *   (a) VALID JSON          — JSON.parse must not throw.
 *   (b) IDENTICAL BASE KEYS — flattened dotted keys with plural suffixes stripped
 *                             must match en exactly (missing AND extra reported).
 *   (c) REQUIRED PLURALS    — for every plural base key in en, the catalog must
 *                             contain every CLDR suffix in REQUIRED_PLURALS[lng].
 *   (d) PLACEHOLDERS        — every {{token}} set must equal en's set for that key.
 *   (e) ENGLISH LEFTOVER    — best-effort heuristic: a non-en leaf identical to en,
 *                             multi-word (contains a space), >3 chars, ASCII letters,
 *                             not in the brand allow-list → failure (Latin scripts).
 *
 * Takes no args; resolves catalog paths relative to the repo root.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");
const LOCALES = join(ROOT, "frontend", "src", "i18n", "locales");

const LANGS = [
  "en", "de", "fr", "es", "it", "pt", "nl", "ru", "pl", "zh-Hans", "ja", "ko",
];

// Required CLDR plural suffixes per language. ru/pl need the full _one/_few/_many/_other
// set; CJK use a single _other; the rest use _one/_other.
const REQUIRED_PLURALS = {
  en: ["_one", "_other"],
  de: ["_one", "_other"],
  fr: ["_one", "_other"],
  es: ["_one", "_other"],
  it: ["_one", "_other"],
  pt: ["_one", "_other"],
  nl: ["_one", "_other"],
  ru: ["_one", "_few", "_many", "_other"],
  pl: ["_one", "_few", "_many", "_other"],
  "zh-Hans": ["_other"],
  ja: ["_other"],
  ko: ["_other"],
};

const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;
const PLACEHOLDER_RE = /\{\{\s*([\w-]+)\s*\}\}/g;

// Tokens that legitimately appear identical across languages (brands, product
// names, codes, technical loanwords). A phrase made ENTIRELY of these tokens
// (plus punctuation/placeholders) is not flagged as untranslated.
const ALLOW_IDENTICAL = new Set([
  "IPMIDeck", "IPMI", "BMC", "FRU", "SEL", "FanPilot", "iDRAC", "iLO",
  "OK", "ID", "CSV", "RAM", "CPU", "DIMM", "PSU", "LAN", "Redfish",
  "Dell", "HP", "HPE", "Supermicro", "Host", "IP", "Backplane",
  // Phase 4: universally-identical networking/crypto/protocol acronyms.
  "HTTPS", "HTTP", "TLS", "SSL", "kWh", "TCP", "UDP", "DNS", "URL", "API",
]);

// Tokens stripped before the per-word allow-list check (punctuation/separators
// and i18next interpolation placeholders carry no translatable content).
function contentWords(value) {
  return value
    .replace(/\{\{\s*[\w-]+\s*\}\}/g, " ") // drop placeholders
    .split(/[\s/—–-]+/)                     // split on spaces and separators
    .map((w) => w.replace(/[.,:;!?()"']/g, "").trim())
    .filter((w) => w.length > 0);
}

/** True when every content word is in the brand/technical allow-list. */
function allBrandTokens(value) {
  const words = contentWords(value);
  if (words.length === 0) return true;
  return words.every((w) => ALLOW_IDENTICAL.has(w));
}

function loadJson(lng) {
  const path = join(LOCALES, lng, "translation.json");
  const raw = readFileSync(path, "utf8");
  return JSON.parse(raw); // may throw — caught by caller
}

/** Flatten a nested object into a map of dotted-key → leaf string value. */
function flatten(obj, prefix = "", out = {}) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) {
      flatten(v, key, out);
    } else {
      out[key] = v;
    }
  }
  return out;
}

/** Strip a trailing plural suffix from the LAST path segment only. */
function baseKey(dottedKey) {
  const idx = dottedKey.lastIndexOf(".");
  const head = idx === -1 ? "" : dottedKey.slice(0, idx + 1);
  const tail = idx === -1 ? dottedKey : dottedKey.slice(idx + 1);
  return head + tail.replace(PLURAL_SUFFIX, "");
}

function placeholders(value) {
  if (typeof value !== "string") return new Set();
  const set = new Set();
  let m;
  PLACEHOLDER_RE.lastIndex = 0;
  while ((m = PLACEHOLDER_RE.exec(value)) !== null) set.add(m[1]);
  return set;
}

function setEq(a, b) {
  if (a.size !== b.size) return false;
  for (const x of a) if (!b.has(x)) return false;
  return true;
}

const failures = [];
function fail(lng, msg) {
  failures.push(`[${lng}] ${msg}`);
}

// --- Load + flatten the master (en) ---
let enFlat;
try {
  enFlat = flatten(loadJson("en"));
} catch (e) {
  console.error(`FATAL: cannot parse en/translation.json: ${e.message}`);
  process.exit(1);
}

const enKeys = Object.keys(enFlat);
const enBaseKeys = new Set(enKeys.map(baseKey));

// Plural base-key families present in en (base key that has at least one plural variant).
const enPluralBases = new Set();
for (const k of enKeys) {
  if (PLURAL_SUFFIX.test(k.slice(k.lastIndexOf(".") + 1))) {
    enPluralBases.add(baseKey(k));
  }
}

for (const lng of LANGS) {
  // (a) VALID JSON
  let flat;
  try {
    flat = flatten(loadJson(lng));
  } catch (e) {
    fail(lng, `invalid JSON: ${e.message}`);
    continue;
  }

  const keys = Object.keys(flat);
  const baseKeys = new Set(keys.map(baseKey));

  // (b) IDENTICAL BASE KEY SET
  for (const bk of enBaseKeys) {
    if (!baseKeys.has(bk)) fail(lng, `missing base key: ${bk}`);
  }
  for (const bk of baseKeys) {
    if (!enBaseKeys.has(bk)) fail(lng, `extra base key not in en: ${bk}`);
  }

  // Build the catalog's present plural suffixes per base key.
  const presentSuffixes = new Map(); // base → Set(suffix)
  for (const k of keys) {
    const tail = k.slice(k.lastIndexOf(".") + 1);
    const m = tail.match(PLURAL_SUFFIX);
    if (m) {
      const bk = baseKey(k);
      if (!presentSuffixes.has(bk)) presentSuffixes.set(bk, new Set());
      presentSuffixes.get(bk).add(`_${m[1]}`);
    }
  }

  // (c) REQUIRED PLURAL FORMS
  const required = REQUIRED_PLURALS[lng] ?? ["_one", "_other"];
  for (const bk of enPluralBases) {
    const have = presentSuffixes.get(bk) ?? new Set();
    for (const suf of required) {
      if (!have.has(suf)) {
        fail(lng, `missing required plural form ${suf} for base key: ${bk}`);
      }
    }
  }

  // (d) PLACEHOLDERS PRESERVED — compare per exact key that exists in both.
  for (const k of enKeys) {
    if (!(k in flat)) continue; // (b)/(c) already reported the gap
    const enSet = placeholders(enFlat[k]);
    const lngSet = placeholders(flat[k]);
    if (!setEq(enSet, lngSet)) {
      fail(
        lng,
        `placeholder mismatch at ${k}: en={${[...enSet].join(",")}} catalog={${[...lngSet].join(",")}}`
      );
    }
  }

  // (e) ENGLISH LEFTOVER (heuristic) — non-en catalogs only.
  if (lng !== "en") {
    for (const k of enKeys) {
      if (!(k in flat)) continue;
      const enVal = enFlat[k];
      const val = flat[k];
      if (typeof enVal !== "string" || typeof val !== "string") continue;
      if (val !== enVal) continue; // translated (or at least differs)
      if (val.length <= 3) continue;
      if (!/[A-Za-z]/.test(val)) continue;
      if (ALLOW_IDENTICAL.has(val.trim())) continue;
      // Only flag multi-word English phrases (a space) — single brand tokens allowed.
      if (!/\s/.test(val.trim())) continue;
      // A phrase made entirely of brand/technical/loanword tokens is legitimately
      // identical across languages (e.g. "Dell iDRAC", "HP iLO", "Host / IP").
      if (allBrandTokens(val)) continue;
      fail(lng, `untranslated English phrase at ${k}: "${val}"`);
    }
  }
}

if (failures.length > 0) {
  console.error("i18n parity FAILED:\n");
  for (const f of failures) console.error("  " + f);
  console.error(`\n${failures.length} failure(s).`);
  process.exit(1);
}

console.log("i18n parity OK");
process.exit(0);
