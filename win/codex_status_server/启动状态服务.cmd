@echo off
setlocal
attrib +h "%~dp0.internal" >nul 2>nul
if exist "%~dp0.runtime" attrib +h "%~dp0.runtime" >nul 2>nul
set "HOST_NAME=127.0.0.1"
if /I "%~1"=="lan" set "HOST_NAME=0.0.0.0"
if not "%CODEX_STATUS_HOST%"=="" set "HOST_NAME=%CODEX_STATUS_HOST%"
powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0.internal\start-server-background.ps1" -HostName "%HOST_NAME%"
exit /b %errorlevel%
