#!/usr/bin/env node
/**
 * SPA build gate (02.2-05 Task 2).
 *
 * Asserts the served React SPA in backend/static is a fresh i18n-aware build:
 *   1. backend/static/index.html exists and references hashed assets under "assets/".
 *   2. backend/static/assets exists and holds >= 2 .js files total.
 *   3. >= 3 DISTINCT per-language catalog lazy chunks are emitted. Each language
 *      catalog is dynamic-import()ed (resourcesToBackend) so Vite emits one hashed
 *      chunk per catalog whose filename embeds the "translation" marker
 *      (translation-<hash>.js). At least 3 distinct such chunks must exist.
 *
 * Prints a one-line OK on success, otherwise prints the failing assertion and
 * process.exit(1). Takes no args; resolves paths relative to the repo root.
 */

import { existsSync, readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");
const STATIC = join(ROOT, "backend", "static");
const INDEX = join(STATIC, "index.html");
const ASSETS = join(STATIC, "assets");

function fail(msg) {
  console.error(`SPA build check FAILED: ${msg}`);
  process.exit(1);
}

// (1) index.html exists and references assets/
if (!existsSync(INDEX)) {
  fail(`missing ${INDEX}`);
}
const indexHtml = readFileSync(INDEX, "utf8");
if (!indexHtml.includes("assets/")) {
  fail("backend/static/index.html does not reference any hashed asset under 'assets/'");
}

// (2) assets/ exists with >= 2 .js files total
if (!existsSync(ASSETS)) {
  fail(`missing ${ASSETS}`);
}
const files = readdirSync(ASSETS);
const jsFiles = files.filter((f) => f.endsWith(".js"));
if (jsFiles.length < 2) {
  fail(`backend/static/assets has only ${jsFiles.length} .js file(s); need >= 2`);
}

// (3) >= 3 DISTINCT per-language catalog lazy chunks (translation-<hash>.js)
const catalogChunks = new Set(
  jsFiles.filter((f) => /(^|[^A-Za-z])translation-[^/]*\.js$/i.test(f))
);
if (catalogChunks.size < 3) {
  fail(
    `found ${catalogChunks.size} distinct per-language catalog chunk(s) (translation-*.js); need >= 3`
  );
}

// Confirm index.html points at a hashed entry chunk under assets/.
if (!/assets\/index-[^"']+\.js/.test(indexHtml)) {
  fail("backend/static/index.html does not reference a hashed assets/index-*.js entry chunk");
}

console.log(
  `SPA build OK: ${jsFiles.length} JS assets, ${catalogChunks.size} distinct per-language catalog chunks`
);
process.exit(0);
