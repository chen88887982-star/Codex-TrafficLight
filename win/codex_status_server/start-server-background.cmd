@echo off
setlocal
cd /d "%~dp0"

start "Codex Status Server" /min powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0server.ps1"

echo Codex status server started in background.
echo Same Windows: http://127.0.0.1:8765/status
echo Log file: %~dp0status-server.log
pause
