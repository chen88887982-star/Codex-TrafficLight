@echo off
setlocal
cd /d "%~dp0"

if "%HOST%"=="" set "HOST=127.0.0.1"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%~dp0server.py"
  goto :done
)

where python >nul 2>nul
if %errorlevel%==0 (
  python "%~dp0server.py"
  goto :done
)

echo Python was not found. Install Python 3 or add Python to PATH.
echo Download: https://www.python.org/downloads/windows/

:done
pause
