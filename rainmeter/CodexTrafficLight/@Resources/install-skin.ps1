param(
  [Parameter(Mandatory = $true)][string]$ProjectRoot,
  [string]$SkinPath = '',
  [string]$SettingsPath = ''
)
$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $ScriptDir 'rainmeter-paths.ps1')
. (Join-Path $ScriptDir 'skin-settings.ps1')
$root = [IO.Path]::GetFullPath($ProjectRoot)
$source = Join-Path $root 'rainmeter\CodexTrafficLight'
$destination = Join-Path (Get-RainmeterSkinPath -SkinPath $SkinPath -SettingsPath $SettingsPath) 'CodexTrafficLight'
if (-not (Test-Path -LiteralPath (Join-Path $source 'CodexTrafficLight.ini'))) { throw 'Source skin not found.' }
if ([IO.Path]::GetFullPath($source).TrimEnd('\') -eq [IO.Path]::GetFullPath($destination).TrimEnd('\')) {
  throw 'The installation target must differ from the source project.'
}
$variables = Join-Path $destination '@Resources\variables.inc'
$backup = $null
if (Test-Path -LiteralPath $variables) {
  $backup = $variables + '.backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
  Copy-Item -LiteralPath $variables -Destination $backup -ErrorAction Stop
}
& robocopy $source $destination /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Skin copy failed (robocopy $LASTEXITCODE). User backup: $backup" }
if ($backup) { Copy-Item -LiteralPath $backup -Destination $variables -Force }
& (Join-Path $destination '@Resources\migrate-installed-variables.ps1') -VariablesPath $variables -ServiceRoot $root
Refresh-CodexSkins
Write-Output "Installed to: $destination"
if ($backup) { Write-Output "Existing settings preserved. Backup: $backup" }
Write-Output 'Load CodexTrafficLight.ini in Rainmeter.'
