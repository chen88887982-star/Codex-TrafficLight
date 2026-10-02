param(
  [Parameter(Mandatory = $true, Position = 0)]
  [ValidateSet("idle", "running", "waiting", "success", "error")]
  [string]$Status,

  [Parameter(Position = 1)]
  [string]$Message = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ServiceDir = Split-Path -Parent $ScriptDir
$RuntimeDir = Join-Path $ServiceDir ".runtime"
$StatusFile = Join-Path $RuntimeDir "status.json"
New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null

if ([string]::IsNullOrWhiteSpace($Message)) {
  $Message = switch ($Status) {
    "idle" { "Codex 空闲" }
    "running" { "Codex 正在执行任务" }
    "waiting" { "等待用户确认" }
    "success" { "任务完成" }
    "error" { "任务失败或异常" }
  }
}

$payload = [ordered]@{
  status = $Status
  message = $Message
  updated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
}

$json = $payload | ConvertTo-Json -Depth 3
Set-Content -LiteralPath $StatusFile -Value $json -Encoding UTF8
Write-Host $json

