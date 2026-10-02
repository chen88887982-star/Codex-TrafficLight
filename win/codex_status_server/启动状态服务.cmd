@echo off
setlocal
attrib +h "%~dp0.internal" >nul 2>nul
if exist "%~dp0.runtime" attrib +h "%~dp0.runtime" >nul 2>nul
if /I "%~1"=="lan" (
  powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0.internal\start-server-background.ps1" -HostName "0.0.0.0"
) else (
  powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0.internal\start-server-background.ps1"
)
exit /b %errorlevel%
