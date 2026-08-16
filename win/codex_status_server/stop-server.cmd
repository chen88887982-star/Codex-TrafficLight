@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-server.ps1"

pause
