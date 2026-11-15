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
 * The range is measured from the merge base of <rev> and <head>, so a base branch that moved on
 * does not show its own changes as untranslated ones.
 *
 * A commit whose subject carries [i18n-skip] exempts the en keys it changed relative to its first
 * parent, and only those: a deliberate en-only change such as a typo fix. Any other stale key in
 * the range still fails, and the exempted keys are printed.
 *
 * Skipped (exit 0) when <rev> is empty, all-zeros or unresolvable — a new branch without a
 * base, a tag push.
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
let base = since;
try {
  base = git("merge-base", since, head).trim() || since;
} catch {
  // unrelated histories: measure from <rev> itself
}

// Each skip-tagged commit exempts the en keys it changed itself, and nothing else.
const exempt = new Set();
const log = git("log", "--no-merges", "--format=%H %s", `${base}..${head}`);
for (const line of log.split("\n")) {
  if (!line.trim()) continue;
  const space = line.indexOf(" ");
  const hash = space === -1 ? line : line.slice(0, space);
  const subject = space === -1 ? "" : line.slice(space + 1);
  if (!subject.includes(SKIP_TOKEN)) continue;
  const parent = catalogAt(`${hash}^`, "en");
  const own = catalogAt(hash, "en");
  const keys = [...new Set([...Object.keys(parent), ...Object.keys(own)])]
    .filter((b) => parent[b] !== own[b])
    .sort();
  for (const b of keys) exempt.add(b);
  console.log(
    `i18n stale check: ${SKIP_TOKEN} in ${hash.slice(0, 7)} ` +
      (keys.length > 0 ? `exempts ${keys.join(", ")}` : "exempts no en string"),
  );
}

const enBefore = catalogAt(base, "en");
const enAfter = catalogAt(head, "en");
const changedAll = Object.keys(enAfter).filter((b) => enBefore[b] !== enAfter[b]);
const changed = changedAll.filter((b) => !exempt.has(b));
const exempted = changedAll.length - changed.length;

const failures = [];
for (const lng of LANGS.filter((l) => l !== "en")) {
  const before = catalogAt(base, lng);
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
    `\n${failures.length} failure(s). Update the translations, or, when the en change needs no` +
      ` translation (such as a typo fix), put ${SKIP_TOKEN} in the subject of the commit that` +
      " made that change; it exempts only the strings that commit changed.",
  );
  process.exit(1);
}
console.log(
  `i18n stale check OK (${changed.length} en key(s) changed, all translated; ` +
    `${exempted} exempted by ${SKIP_TOKEN})`,
);
