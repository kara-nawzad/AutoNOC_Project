# ============================================================
#  Start-Demo.ps1 - start the AutoNOC demo server (detached)
# ============================================================
#  The server runs in the background and keeps running even if
#  you close every PowerShell window. Nothing you type can stop
#  it. To stop it later, run Stop-Demo.ps1.
#
#  RUN (in any PowerShell, from anywhere):
#     Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#     .\Start-Demo.ps1
# ============================================================

$ErrorActionPreference = "Continue"
# Resolve the project root relative to this script's own location, so the
# launcher works from any clone/path. Fall back to PWD if $PSScriptRoot is empty
# (e.g. Windows PowerShell < 3, or when invoked from an older host).
$root = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$py = Join-Path $root "venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "venv python not found at $py" -ForegroundColor Red
    Write-Host "Looking for python on PATH instead..."
    $py = "python"
}

Write-Host "=== AutoNOC demo launcher ===" -ForegroundColor Cyan

# 1. stop any leftover server on port 8000
$busy = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Write-Host "  closing old server on port 8000..." -ForegroundColor Yellow
    $busy | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 800
}

# 2. demo seed + auto-enable the AI (inherited by the child process)
$env:AUTONOC_SEED = "131"
$env:AUTONOC_AI   = "1"

# 3. launch the server DETACHED (hidden window, logs to files)
$out = Join-Path $root "server.log"
$err = Join-Path $root "server.err"
Remove-Item $out, $err -ErrorAction SilentlyContinue

Write-Host "  starting server in the background (seed 131, AI on)..." -ForegroundColor Yellow
Start-Process -FilePath $py `
    -ArgumentList @("-m","uvicorn","autonoc.api.main:app","--port","8000") `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $out `
    -RedirectStandardError $err

# 4. wait and verify
Start-Sleep -Seconds 6
try {
    $h = (Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/health" -UseBasicParsing -TimeoutSec 6).Content | ConvertFrom-Json
    Write-Host ""
    Write-Host "  SERVER IS RUNNING" -ForegroundColor Green
    Write-Host "    seed   : $($h.seed)"
    Write-Host "    tick   : $($h.tick)"
    Write-Host "    ai     : $($h.ai_enabled)"
    Write-Host "    policy : $($h.ai_policy)"
} catch {
    Write-Host ""
    Write-Host "  Server did NOT start. Here is server.err:" -ForegroundColor Red
    if (Test-Path $err) { Get-Content $err -Tail 25 }
    if (Test-Path $out) { Write-Host "--- server.log ---"; Get-Content $out -Tail 10 }
}

# 5. open the dashboard (127.0.0.1, not localhost - avoids IPv6 issues
#    that can make fetch() fail with NetworkError)
Start-Process "http://127.0.0.1:8000"
Write-Host ""
Write-Host "  Browser should open http://127.0.0.1:8000" -ForegroundColor Cyan
Write-Host "  If it does not, open http://127.0.0.1:8000 yourself."
Write-Host "  IMPORTANT: if the page still looks empty, press Ctrl+F5 once"
Write-Host "  to force the browser to drop its old cached copy."
Write-Host "  You can close ALL PowerShell windows now - the server"
Write-Host "  keeps running. To stop it:  .\Stop-Demo.ps1"
Write-Host "======================================================"
