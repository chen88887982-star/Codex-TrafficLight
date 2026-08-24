$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ServiceDir = Split-Path -Parent $ScriptDir
$PidFile = Join-Path (Join-Path $ServiceDir ".runtime") "status-server.pid"
$ServerFile = Join-Path $ScriptDir "server.py"

if (-not (Test-Path -LiteralPath $PidFile)) {
  Write-Host "No Codex status server PID file was found."
  exit 0
}

try {
  $record = Get-Content -LiteralPath $PidFile -Raw -Encoding UTF8 | ConvertFrom-Json
  $serverPid = [int]$record.pid
} catch {
  Write-Host "The PID file is invalid; it was not used to stop any process." -ForegroundColor Red
  exit 1
}

$process = Get-CimInstance Win32_Process -Filter "ProcessId = $serverPid" -ErrorAction SilentlyContinue
if ($null -eq $process) {
  Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
  Write-Host "The recorded Codex status server is no longer running."
  exit 0
}

$expectedServer = [regex]::Escape($ServerFile)
if ([string]::IsNullOrWhiteSpace($process.CommandLine) -or $process.CommandLine -notmatch $expectedServer) {
  Write-Host "PID $serverPid belongs to another program; nothing was stopped." -ForegroundColor Red
  Write-Host "Recorded command: $($process.CommandLine)"
  exit 1
}

Stop-Process -Id $serverPid -Force
Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
Write-Host "Stopped Codex status server process $serverPid."
