@echo off
setlocal
cd /d "%~dp0"

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

echo 未找到 Python。请先安装 Python 3，或把 Python 加入 PATH。
echo 下载地址：https://www.python.org/downloads/windows/

:done
pause
