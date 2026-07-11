#!/usr/bin/env node
/**
 * SPA freshness gate.
 *
 * backend/static is COMMITTED and is shipped inside the PyPI wheel
 * ([tool.setuptools.package-data] "backend" = ["static/**\/*"]), so a stale bundle ships a stale
 * UI while the Docker image (which rebuilds the SPA itself) ships the current one. This gate
 * asserts backend/static is BOTH well-formed AND current with frontend/src.
 *
 * Asserts:
 *   1. STRUCTURE
 *      a. backend/static/index.html exists and references hashed assets under "assets/".
 *      b. backend/static/assets exists and holds >= 2 .js files.
 *      c. >= 3 DISTINCT per-language catalog chunks (translation-<hash>.js) — each catalog is
 *         dynamic-import()ed via resourcesToBackend, so Vite emits one hashed chunk per catalog.
 *      d. index.html references a hashed assets/index-*.js entry chunk.
 *   2. FRESHNESS (authoritative)
 *      Runs `vite build` from frontend/ into a THROWAWAY temp dir and asserts the emitted asset
 *      filename set (Vite content hashes) is IDENTICAL to backend/static/assets, and that
 *      index.html references the same asset set. Any drift = the committed bundle was not built
 *      from the current frontend/src.
 *
 * Non-mutating: writes only to an mkdtemp() dir under os.tmpdir(), removed on every exit path.
 * Never writes backend/static or frontend/dist.
 *
 * Cross-platform reproducible: verified to emit an identical asset set on Windows/Node 24/CRLF
 * worktree and on Linux/Node 20/LF checkout (gate.yml), so it is safe in pre-commit AND in CI.
 *
 * Fix on failure: pwsh -File scripts/rebuild-spa.ps1
 */

import { existsSync, readFileSync, readdirSync, mkdtempSync, rmSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { tmpdir } from "node:os";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");
const STATIC = join(ROOT, "backend", "static");
const INDEX = join(STATIC, "index.html");
const ASSETS = join(STATIC, "assets");
const FRONTEND = join(ROOT, "frontend");
const VITE_BIN = join(FRONTEND, "node_modules", "vite", "bin", "vite.js");

const REBUILD_HINT =
  "Rebuild the served SPA:  pwsh -File scripts/rebuild-spa.ps1  " +
  "(clean -> npm run build -> copy frontend/dist/* into backend/static/), then re-run this check.";

let tmp = null;
function cleanup() {
  if (!tmp) return;
  try {
    rmSync(tmp, { recursive: true, force: true });
  } catch {
    /* best effort */
  }
  tmp = null;
}
function fail(msg) {
  cleanup();
  console.error(`SPA build check FAILED: ${msg}`);
  process.exit(1);
}
const assetRefs = (html) =>
  new Set([...html.matchAll(/assets\/([A-Za-z0-9._-]+)/g)].map((m) => m[1]));

/* ---- (1) STRUCTURE ---- */

if (!existsSync(INDEX)) fail(`missing ${INDEX}`);
const indexHtml = readFileSync(INDEX, "utf8");
if (!indexHtml.includes("assets/"))
  fail("backend/static/index.html does not reference any hashed asset under 'assets/'");

if (!existsSync(ASSETS)) fail(`missing ${ASSETS}`);
const files = readdirSync(ASSETS);
const jsFiles = files.filter((f) => f.endsWith(".js"));
if (jsFiles.length < 2)
  fail(`backend/static/assets has only ${jsFiles.length} .js file(s); need >= 2`);

const catalogChunks = new Set(
  jsFiles.filter((f) => /(^|[^A-Za-z])translation-[^/]*\.js$/i.test(f))
);
if (catalogChunks.size < 3)
  fail(
    `found ${catalogChunks.size} distinct per-language catalog chunk(s) (translation-*.js); need >= 3`
  );

if (!/assets\/index-[^"']+\.js/.test(indexHtml))
  fail("backend/static/index.html does not reference a hashed assets/index-*.js entry chunk");

/* ---- (2) FRESHNESS ---- */

if (!existsSync(VITE_BIN))
  fail(`missing ${VITE_BIN} — run \`npm ci\` in frontend/ before this check`);

tmp = mkdtempSync(join(tmpdir(), "spa-freshness-"));
const build = spawnSync(
  process.execPath,
  [VITE_BIN, "build", "--outDir", tmp.replace(/\\/g, "/"), "--emptyOutDir"],
  { cwd: FRONTEND, encoding: "utf8" }
);
if (build.status !== 0)
  fail(
    `reference \`vite build\` failed (exit ${build.status}):\n${build.stderr || build.stdout || "(no output)"}`
  );

const tmpAssets = join(tmp, "assets");
const tmpIndex = join(tmp, "index.html");
if (!existsSync(tmpAssets) || !existsSync(tmpIndex))
  fail(`reference build emitted no index.html/assets in ${tmp}`);

const fresh = new Set(readdirSync(tmpAssets));
const served = new Set(files);
const missing = [...fresh].filter((f) => !served.has(f)).sort();
const extra = [...served].filter((f) => !fresh.has(f)).sort();
if (missing.length || extra.length)
  fail(
    "backend/static is STALE — it was NOT built from the current frontend/src.\n" +
      (missing.length
        ? `  missing from backend/static/assets (${missing.length}): ${missing.join(", ")}\n`
        : "") +
      (extra.length
        ? `  stale/extra in backend/static/assets (${extra.length}): ${extra.join(", ")}\n`
        : "") +
      `  ${REBUILD_HINT}`
  );

const freshRefs = assetRefs(readFileSync(tmpIndex, "utf8"));
const servedRefs = assetRefs(indexHtml);
const refMissing = [...freshRefs].filter((f) => !servedRefs.has(f)).sort();
const refExtra = [...servedRefs].filter((f) => !freshRefs.has(f)).sort();
if (refMissing.length || refExtra.length)
  fail(
    "backend/static/index.html references a STALE asset set.\n" +
      `  expected: ${[...freshRefs].sort().join(", ")}\n` +
      `  actual:   ${[...servedRefs].sort().join(", ")}\n` +
      `  ${REBUILD_HINT}`
  );

cleanup();
console.log(
  `SPA build OK: ${served.size} assets (${jsFiles.length} JS, ${catalogChunks.size} catalog chunks) ` +
    `match a clean vite build of frontend/src`
);
process.exit(0);
