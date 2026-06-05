# SAFE static-SPA rebuild (assert-path-inside-repo -> clean -> build -> copy).
# Reusable, idempotent. Documented #1 deploy footgun is a stale backend/static
# bundle: backend/static is committed and served by FastAPI, so the served SPA
# must be rebuilt from the i18n source after any frontend source change.
#
# Steps:
#   1. CLEAN (SAFE): resolve absolute backend/static, ASSERT it is inside the
#      repo root (abort if not), tolerate a missing assets/ dir, remove only
#      assets/* + index.html, recreate assets/ before copy.
#   2. BUILD: cd frontend; npm run build  (tsc -b && vite build -> frontend/dist).
#   3. COPY: copy frontend/dist/* into backend/static/.
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path "C:/path/to/IPMI-FanPilot").Path
$staticDir = Join-Path $repoRoot "backend/static"
$staticResolved = (Resolve-Path $staticDir).Path

# SAFETY: refuse to delete anything outside the repo root
if (-not $staticResolved.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
  Write-Error "ABORT: resolved static path '$staticResolved' is not inside repo root '$repoRoot'"
  exit 1
}

$assetsDir = Join-Path $staticResolved "assets"
# tolerate a missing assets/ dir (no error if absent)
if (Test-Path $assetsDir) { Remove-Item -Recurse -Force (Join-Path $assetsDir "*") }
$indexHtml = Join-Path $staticResolved "index.html"
if (Test-Path $indexHtml) { Remove-Item -Force $indexHtml }
# recreate assets/ before copy (idempotent)
if (-not (Test-Path $assetsDir)) { New-Item -ItemType Directory -Path $assetsDir | Out-Null }

Write-Output "CLEAN OK: emptied assets/* + removed built index.html under $staticResolved"

# BUILD
Set-Location (Join-Path $repoRoot "frontend")
npm run build
if ($LASTEXITCODE -ne 0) { Write-Error "ABORT: npm run build failed (exit $LASTEXITCODE)"; exit $LASTEXITCODE }

# COPY frontend/dist/* into backend/static/
Copy-Item -Recurse -Force (Join-Path $repoRoot "frontend/dist/*") $staticResolved

Write-Output "COPY OK: frontend/dist/* -> $staticResolved"
