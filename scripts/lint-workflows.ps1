# Static-lint all GitHub Actions workflows with actionlint (pinned 1.7.12) via its Docker image
# (bundles shellcheck for embedded run: scripts). Requires Docker Desktop running.
$ErrorActionPreference = "Stop"
docker run --rm -v "${PWD}:/repo" -w /repo rhysd/actionlint:1.7.12 -color
if ($LASTEXITCODE -ne 0) { throw "actionlint failed (exit $LASTEXITCODE)" }
Write-Host "actionlint: all workflows valid"
