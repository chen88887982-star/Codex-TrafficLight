param([string]$TaskName = "CodexTrafficLight-Status-8765")
$ErrorActionPreference = "Stop"
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
  Write-Output "[OK] 已删除登录自启动任务：$TaskName"
} else {
  Write-Output "[OK] 登录自启动任务不存在，无需删除。"
}
