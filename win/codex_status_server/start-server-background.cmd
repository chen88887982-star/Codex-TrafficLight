@echo off
setlocal
cd /d "%~dp0"

if "%HOST%"=="" set "HOST=127.0.0.1"

where py >nul 2>nul
if %errorlevel%==0 (
  start "Codex Status Server" /min py -3 "%~dp0server.py"
  goto :done
)

where python >nul 2>nul
if %errorlevel%==0 (
  start "Codex Status Server" /min python "%~dp0server.py"
  goto :done
)

echo Python was not found. Install Python 3 or add Python to PATH.
echo Download: https://www.python.org/downloads/windows/
pause
exit /b 1

:done
echo Codex status server started in background.
echo Same Windows: http://127.0.0.1:8765/status
echo LAN mode: use start-server-lan.cmd
echo Log file: %~dp0status-server.log
pause
