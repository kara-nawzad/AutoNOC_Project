# AutoNOC diagnostic - run with:  .\diag.ps1
# Prints a complete health check of the backend in ~15 seconds.
$ErrorActionPreference = "Continue"
# Resolve the project root relative to this script's own location.
$root = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }

Write-Host "=== AutoNOC DIAGNOSTIC ===" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1] Python:" -ForegroundColor Yellow
try { python --version } catch { Write-Host "  FAIL: python not found" }

Write-Host ""
Write-Host "[2] Project files:" -ForegroundColor Yellow
$files = @(
  "autonoc\api\main.py",
  "autonoc\engine\engine.py",
  "autonoc\web\app.js",
  "install_autonoc.py",
  "tests\test_polish.py"
)
foreach ($f in $files) {
  if (Test-Path (Join-Path $root $f)) { Write-Host "  OK   $f" }
  else { Write-Host "  MISS $f" }
}

Write-Host ""
Write-Host "[3] Port 8000:" -ForegroundColor Yellow
$conn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($conn) { Write-Host "  LISTENING (pid $($conn.OwningProcess))" }
else { Write-Host "  NOT LISTENING - server is not running" }

Write-Host ""
Write-Host "[4] HTTP endpoints:" -ForegroundColor Yellow
$urls = @("http://localhost:8000/api/health", "http://127.0.0.1:8000/api/health")
foreach ($url in $urls) {
  try {
    $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
    Write-Host "  OK   $url -> $($r.StatusCode)  $($r.Content)"
  } catch {
    Write-Host "  FAIL $url -> $($_.Exception.Message)"
  }
}

Write-Host ""
Write-Host "[5] Is the simulation advancing?" -ForegroundColor Yellow
try {
  $a = (Invoke-WebRequest -Uri "http://localhost:8000/api/health" -UseBasicParsing -TimeoutSec 5).Content | ConvertFrom-Json
  Write-Host "  tick now : $($a.tick)"
  Start-Sleep -Seconds 5
  $b = (Invoke-WebRequest -Uri "http://localhost:8000/api/health" -UseBasicParsing -TimeoutSec 5).Content | ConvertFrom-Json
  Write-Host "  tick +5s : $($b.tick)"
  if ($b.tick -gt $a.tick) { Write-Host "  -> SIM IS ADVANCING (server alive)" }
  else { Write-Host "  -> tick NOT advancing - paused or stuck" }
} catch {
  Write-Host "  cannot reach server for tick check"
}

Write-Host ""
Write-Host "[6] Does the app import?" -ForegroundColor Yellow
Push-Location $root
try { python -c "from autonoc.api import main; print('  import OK')" }
catch { Write-Host "  import FAILED: $($_.Exception.Message)" }
Pop-Location

Write-Host ""
Write-Host "=== DONE - paste this whole output back to me ===" -ForegroundColor Cyan
