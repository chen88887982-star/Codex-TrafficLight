param([int]$Port = 8767)
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $ScriptDir 'service-settings.ps1')
if (-not $PSBoundParameters.ContainsKey('Port')) { $Port = (Get-ServiceLaunchSettings (Split-Path -Parent $ScriptDir)).Port }
try {
  $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 3
} catch {
  Write-Error "$Port 状态服务不可访问：$($_.Exception.Message)"
  exit 1
}
if ($health.service -ne "codex-traffic-light-status") {
  Write-Error "端口 $Port 返回了未知服务：$($health.service)"
  exit 1
}
$health | ConvertTo-Json -Depth 6
if ($health.service_version -ne '0.5.1' -or [int]$health.protocol_version -ne 2) {
  Write-Error '服务版本或协议不匹配。请先只读体检，再按提示修复。'
  exit 1
}
if ($health.status -notin @('ok', 'degraded')) { exit 2 }
exit 0
