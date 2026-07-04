# Repeatable D-06 Docker image smoke — requires Docker Desktop running (executed at the Plan 09-05 checkpoint).
$ErrorActionPreference = "Stop"
$img = "ipmideck:smoke"; $name = "ipmideck-smoke"; $vol = "ipmideck-smoke-data"
$rev = (git rev-parse HEAD).Trim()

# 1. build from clean checkout with the same build-args CI's metadata-action would pass
docker build --build-arg VERSION=2.0.0 --build-arg REVISION=$rev -t $img .

# 2. run demo mode, throwaway volume, PORT MAPPING (host networking is a no-op on Windows)
docker rm -f $name 2>$null; docker volume rm $vol 2>$null
docker run -d --name $name -p 3000:3000 -e IPMIDECK_DEMO=true -v "${vol}:/data" $img

# 3. health poll (200) — up to ~30s
$ok = $false
foreach ($i in 1..30) {
  try { if ((Invoke-WebRequest http://localhost:3000/api/health -UseBasicParsing).StatusCode -eq 200) { $ok=$true; break } } catch {}
  Start-Sleep 1
}
if (-not $ok) { throw "health never 200" }

# 4. version consistency: /api/health reports 2.0.0 (wheel via importlib.metadata)
$health = Invoke-RestMethod http://localhost:3000/api/health
if ($health.version -ne "2.0.0") { throw "health version $($health.version) != 2.0.0" }

# 5. SPA served (index references hashed assets/)
$root = (Invoke-WebRequest http://localhost:3000/ -UseBasicParsing).Content
if ($root -notmatch "assets/index-") { throw "SPA not served" }

# 6. ipmitool present in container
docker exec $name ipmitool -V

# 7. 6 demo vendor servers — query the DB (sidesteps auth on /api/servers)
$n = docker exec $name python -c "import sqlite3;print(sqlite3.connect('/data/ipmideck.db').execute('select count(*) from servers').fetchone()[0])"
if ([int]$n -ne 6) { throw "expected 6 demo servers, got $n" }

# 8. restart persistence: /data survives (DB rows + config)
docker restart $name
foreach ($i in 1..30) { try { if ((Invoke-WebRequest http://localhost:3000/api/health -UseBasicParsing).StatusCode -eq 200) { break } } catch {}; Start-Sleep 1 }
$n2 = docker exec $name python -c "import sqlite3;print(sqlite3.connect('/data/ipmideck.db').execute('select count(*) from servers').fetchone()[0])"
if ([int]$n2 -ne 6) { throw "servers not persisted after restart ($n2)" }
docker exec $name sh -c "test -f /data/config.yaml"   # config persisted
Write-Host "PERSIST OK"

# 9. OCI label + size report (D-13)
docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.version" }}' $img
docker images $img --format "IMAGE SIZE: {{.Size}}"

# 10. leaked-file hygiene (SC-5): none of the local-only files inside the image
docker exec $name sh -c "! find / -name PRD.md -o -name '*.tmp' -o -name CLAUDE.md 2>/dev/null | grep -q ."

# cleanup
docker rm -f $name; docker volume rm $vol; docker rmi $img
Write-Host "SMOKE OK — build+boot+demo+persistence+hygiene all green"
