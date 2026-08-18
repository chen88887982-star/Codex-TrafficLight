@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-login-autostart.ps1"
exit /b %errorlevel%
