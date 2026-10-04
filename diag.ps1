# AutoNOC diagnostic - run from PowerShell with: .\diag.ps1
# Checks the current React frontend, backend, committed model artifacts, and a local server.
$ErrorActionPreference = "Continue"
$root = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }

Write-Host "=== AutoNOC DIAGNOSTIC ===" -ForegroundColor Cyan
Write-Host "Project: $root"
Write-Host ""

Write-Host "[1] Python runtime:" -ForegroundColor Yellow
$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
  python --version
} else {
  Write-Host "  FAIL: python not found on PATH" -ForegroundColor Red
}

Write-Host ""
Write-Host "[2] Backend, frontend, tests, and required model files:" -ForegroundColor Yellow
$files = @(
  "autonoc\api\main.py",
  "autonoc\engine\engine.py",
  "autonoc\engine\config.py",
  "frontend\package.json",
  "frontend\package-lock.json",
  "frontend\src\App.tsx",
  "frontend\src\components\NetworkMap.tsx",
  "frontend\src\components\StreetBasemap.tsx",
  "models\doctor_xgb.json",
  "models\doctor_scaler.npz",
  "models\feature_order.json",
  "models\oracle_gru.pt",
  "models\oracle_stats.npz",
  "requirements.txt",
  "tests\test_dashboard.py"
)
foreach ($file in $files) {
  if (Test-Path (Join-Path $root $file)) { Write-Host "  OK   $file" }
  else { Write-Host "  MISS $file" -ForegroundColor Red }
}

Write-Host ""
Write-Host "[3] Frontend build:" -ForegroundColor Yellow
$distIndex = Join-Path $root "autonoc\web\dist\index.html"
if (Test-Path $distIndex) {
  Write-Host "  OK   autonoc\web\dist\index.html"
} else {
  Write-Host "  INFO React bundle is not built yet. Run npm ci --prefix frontend, then npm run build --prefix frontend."
}

Write-Host ""
Write-Host "[4] Local server on port 8000:" -ForegroundColor Yellow
$conn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($conn) {
  Write-Host "  LISTENING (pid $($conn[0].OwningProcess))" -ForegroundColor Green
} else {
  Write-Host "  NOT LISTENING - start the API before checking HTTP or tick advancement"
}

Write-Host ""
Write-Host "[5] HTTP health endpoint:" -ForegroundColor Yellow
$healthUrl = "http://127.0.0.1:8000/api/health"
try {
  $health = (Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 5).Content | ConvertFrom-Json
  Write-Host "  OK   $healthUrl"
  Write-Host "  tick=$($health.tick) seed=$($health.seed) ai=$($health.ai_enabled) paused=$($health.paused) run_id=$($health.run_id)"
} catch {
  Write-Host "  FAIL $healthUrl -> $($_.Exception.Message)"
  $health = $null
}

if ($health -and -not $health.paused) {
  Write-Host ""
  Write-Host "[6] Simulation advancement (5 seconds):" -ForegroundColor Yellow
  Start-Sleep -Seconds 5
  try {
    $next = (Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 5).Content | ConvertFrom-Json
    if ($next.tick -gt $health.tick) {
      Write-Host "  OK   tick $($health.tick) -> $($next.tick)" -ForegroundColor Green
    } else {
      Write-Host "  INFO tick did not advance; the simulation may be paused or resetting"
    }
  } catch {
    Write-Host "  FAIL could not re-read health: $($_.Exception.Message)"
  }
} elseif ($health) {
  Write-Host ""
  Write-Host "[6] Simulation advancement: skipped because the simulation is paused"
}

Write-Host ""
Write-Host "[7] Backend import:" -ForegroundColor Yellow
if ($python) {
  Push-Location $root
  python -c "from autonoc.api import main"
  $importExitCode = $LASTEXITCODE
  Pop-Location
  if ($importExitCode -eq 0) {
    Write-Host "  import OK" -ForegroundColor Green
  } else {
    Write-Host "  import FAILED (python exit code $importExitCode)" -ForegroundColor Red
  }
} else {
  Write-Host "  SKIP: python is not available"
}

Write-Host ""
Write-Host "=== DIAGNOSTIC COMPLETE ===" -ForegroundColor Cyan
