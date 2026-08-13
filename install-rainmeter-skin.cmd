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

set "USER_VARIABLES=%DST%\@Resources\variables.inc"
set "VARIABLES_BACKUP="
if exist "%USER_VARIABLES%" (
  for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "STAMP=%%I"
  set "VARIABLES_BACKUP=%DST%\@Resources\variables.inc.backup-%STAMP%"
  copy /Y "%USER_VARIABLES%" "%VARIABLES_BACKUP%" >nul
)

robocopy "%SRC%" "%DST%" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo Failed to copy Rainmeter skin.
  pause
  exit /b 1
)

if defined VARIABLES_BACKUP (
  copy /Y "%VARIABLES_BACKUP%" "%USER_VARIABLES%" >nul
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$p='%USER_VARIABLES%'; $c=Get-Content -LiteralPath $p -Raw -Encoding Unicode; if ($c -match '(?m)^SkinHeight=(568|716)\s*$') { $c=$c -replace '(?m)^SkinHeight=(568|716)\s*$','SkinHeight=736'; Set-Content -LiteralPath $p -Value $c -Encoding Unicode }"
)

echo Installed to:
echo %DST%
if defined VARIABLES_BACKUP (
  echo Existing user variables preserved.
  echo Legacy 568px or 716px height is upgraded to 736px for the task card.
  echo Backup:
  echo %VARIABLES_BACKUP%
)
echo.
echo Open Rainmeter, refresh all skins, then load CodexTrafficLight.ini.
pause
