@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall-login-autostart.ps1"
exit /b %errorlevel%
