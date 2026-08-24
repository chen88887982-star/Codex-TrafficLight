param([int]$Port = 8767)
$ErrorActionPreference = "Stop"
try {
  $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 3
} catch {
  Write-Error "8767 状态服务不可访问：$($_.Exception.Message)"
  exit 1
}
if ($health.service -ne "codex-traffic-light-status") {
  Write-Error "端口 $Port 返回了未知服务：$($health.service)"
  exit 1
}
$health | ConvertTo-Json -Depth 6
if ($health.status -eq "error") { exit 2 }
exit 0
