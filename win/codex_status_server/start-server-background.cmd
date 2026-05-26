@echo off
setlocal
cd /d "%~dp0"

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

echo 未找到 Python。请先安装 Python 3，或把 Python 加入 PATH。
echo 下载地址：https://www.python.org/downloads/windows/
pause
exit /b 1

:done
echo Codex status server started in background.
echo Same Windows: http://127.0.0.1:8765/status
echo Log file: %~dp0status-server.log
pause
