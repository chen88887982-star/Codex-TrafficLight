@echo off
setlocal
powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0start-server-background.ps1" -HostName 127.0.0.1
exit /b %errorlevel%
