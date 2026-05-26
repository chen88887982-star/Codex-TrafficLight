@echo off
setlocal

set "SRC=%~dp0rainmeter\CodexTrafficLight"
set "DST=%USERPROFILE%\Documents\Rainmeter\Skins\CodexTrafficLight"

if not exist "%SRC%\CodexTrafficLight.ini" (
  echo Source skin not found: %SRC%
  pause
  exit /b 1
)

if not exist "%USERPROFILE%\Documents\Rainmeter\Skins" (
  mkdir "%USERPROFILE%\Documents\Rainmeter\Skins"
)

robocopy "%SRC%" "%DST%" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo Failed to copy Rainmeter skin.
  pause
  exit /b 1
)

echo Installed to:
echo %DST%
echo.
echo Open Rainmeter, refresh all skins, then load CodexTrafficLight.ini.
pause
