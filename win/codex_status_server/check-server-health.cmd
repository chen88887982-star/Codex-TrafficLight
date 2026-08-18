@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0check-server-health.ps1"
exit /b %errorlevel%
