#!/usr/bin/env node
/**
 * Stale-translation gate for the frontend catalogs.
 *
 *   node scripts/check-i18n-stale.mjs --since <rev> [--head <rev>]
 *
 * For every key whose en value changed (or appeared) between <rev> and <head>, every other
 * catalog must change that key in the same range — otherwise the translation still says the
 * old English. Plural variants count as one key (base key with the CLDR suffix stripped).
 * Missing keys are check-i18n-parity.mjs's job, not this one.
 *
 * Skipped (exit 0) when <rev> is empty, all-zeros or unresolvable — a new branch without a
 * base, a tag push — or when a commit message in the range carries [i18n-skip], for a
 * deliberate en-only change such as a typo fix.
 */

import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const CATALOG = (lng) => `frontend/src/i18n/locales/${lng}/translation.json`;
const LANGS = [
  ...readFileSync(join(ROOT, "frontend", "src", "i18n", "languages.ts"), "utf8")
    .matchAll(/\bcode:\s*"([^"]+)"/g),
].map((m) => m[1]);

const SKIP_TOKEN = "[i18n-skip]";
const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;

function arg(name) {
  const i = process.argv.indexOf(name);
  return i === -1 ? "" : (process.argv[i + 1] ?? "");
}

function git(...args) {
  return execFileSync("git", args, {
    cwd: ROOT,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    maxBuffer: 64 * 1024 * 1024,
  });
}

function resolve(rev) {
  if (!rev || /^0+$/.test(rev)) return null;
  try {
    return git("rev-parse", "--verify", "--quiet", `${rev}^{commit}`).trim();
  } catch {
    return null;
  }
}

function flatten(obj, prefix = "", out = {}) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) flatten(v, key, out);
    else out[key] = v;
  }
  return out;
}

function baseKey(dottedKey) {
  const idx = dottedKey.lastIndexOf(".");
  return dottedKey.slice(0, idx + 1) + dottedKey.slice(idx + 1).replace(PLURAL_SUFFIX, "");
}

/** base key → serialized values of all its variants, at a given revision. */
function catalogAt(rev, lng) {
  let flat = {};
  try {
    flat = flatten(JSON.parse(git("show", `${rev}:${CATALOG(lng)}`)));
  } catch {
    // absent or invalid at this revision — parity reports invalid JSON
  }
  const groups = {};
  for (const k of Object.keys(flat).sort()) {
    (groups[baseKey(k)] ??= []).push([k, flat[k]]);
  }
  return Object.fromEntries(Object.entries(groups).map(([b, v]) => [b, JSON.stringify(v)]));
}

const since = resolve(arg("--since"));
const head = resolve(arg("--head") || "HEAD");
if (!since || !head) {
  console.log("i18n stale check skipped (no base revision)");
  process.exit(0);
}
if (git("log", "--format=%B", `${since}..${head}`).includes(SKIP_TOKEN)) {
  console.log(`i18n stale check skipped (${SKIP_TOKEN} in a commit message)`);
  process.exit(0);
}

const enBefore = catalogAt(since, "en");
const enAfter = catalogAt(head, "en");
const changed = Object.keys(enAfter).filter((b) => enBefore[b] !== enAfter[b]);

const failures = [];
for (const lng of LANGS.filter((l) => l !== "en")) {
  const before = catalogAt(since, lng);
  const after = catalogAt(head, lng);
  for (const b of changed) {
    if (after[b] === undefined) continue; // missing key: parity's job
    if (before[b] === after[b]) failures.push(`[${lng}] ${b}: en changed, translation did not`);
  }
}

if (failures.length > 0) {
  console.error("i18n stale check FAILED:\n");
  for (const f of failures) console.error("  " + f);
  console.error(
    `\n${failures.length} failure(s). Update the translations, or add ${SKIP_TOKEN} to a commit` +
      " message if the en change needs no translation (e.g. a typo fix).",
  );
  process.exit(1);
}
console.log(`i18n stale check OK (${changed.length} en key(s) changed, all translated)`);
