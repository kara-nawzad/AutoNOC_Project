@echo off
REM ============================================================
REM  Stop-Demo.bat - stop the AutoNOC demo server
REM ============================================================
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    taskkill /PID %%p /F >nul 2>&1
)
echo Server stopped.
pause
