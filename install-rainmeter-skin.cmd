@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0rainmeter\CodexTrafficLight\@Resources\install-skin.ps1" -ProjectRoot "%~dp0." %*
set "RESULT=%errorlevel%"
if not "%RESULT%"=="0" echo Rainmeter installation failed. See the error above.
pause
exit /b %RESULT%
