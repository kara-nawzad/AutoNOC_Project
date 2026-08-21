@echo off
REM ============================================================
REM  Start-Demo.bat - start the AutoNOC demo server (detached)
REM ============================================================
REM  Double-click this file. The server starts in the background
REM  and your browser opens the dashboard. No PowerShell needed.
REM  To stop it later: double-click Stop-Demo.bat
REM ============================================================
cd /d "%~dp0"

REM close any old server on port 8000
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    taskkill /PID %%p /F >nul 2>&1
)

set AUTONOC_SEED=131
set AUTONOC_AI=1

start "" http://127.0.0.1:8000

echo.
echo ============================================================
echo   AutoNOC demo starting (seed 131, AI on).
echo   Your browser should open http://127.0.0.1:8000
echo.
echo   RULES: keep this window open.
echo          do NOT press Ctrl+C until the demo is over.
echo          do NOT click inside this window.
echo          other commands go in a NEW window.
echo ============================================================
echo.
venv\Scripts\python.exe -m uvicorn autonoc.api.main:app --port 8000
pause
