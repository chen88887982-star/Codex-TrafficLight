param([string]$ServiceRoot)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms

if ([string]::IsNullOrWhiteSpace($ServiceRoot) -or -not (Test-Path -LiteralPath $ServiceRoot -PathType Container)) {
  [System.Windows.Forms.MessageBox]::Show(
    "未找到状态服务项目目录。请重新运行 install-rainmeter-skin.cmd 后再试。",
    "Codex 通知设置",
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Warning
  ) | Out-Null
  exit 1
}

$ProjectRoot = (Resolve-Path -LiteralPath $ServiceRoot).Path
$ConfigPath = Join-Path $ProjectRoot "status-auth.json"
$StartScript = Join-Path $ProjectRoot "win\codex_status_server\.internal\start-server-background.ps1"
$StopScript = Join-Path $ProjectRoot "win\codex_status_server\.internal\stop-server.ps1"
$DoctorScript = Join-Path $ProjectRoot "win\codex_status_server\.internal\service-doctor.ps1"
if (
  -not (Test-Path -LiteralPath $StartScript) -or
  -not (Test-Path -LiteralPath $StopScript) -or
  -not (Test-Path -LiteralPath $DoctorScript)
) {
  throw "状态服务维护脚本不完整。"
}

$settings = [ordered]@{}
if (Test-Path -LiteralPath $ConfigPath) {
  try {
    $existing = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($property in $existing.PSObject.Properties) { $settings[$property.Name] = $property.Value }
  } catch {
    throw "status-auth.json 无法解析，未覆盖原文件：$($_.Exception.Message)"
  }
}

$enabled = $settings["notifications_enabled"] -eq $true
$message = if ($enabled) { "当前通知已启用。是否继续保持启用？选择否将关闭。" } else { "当前通知未启用。是否启用等待确认、完成和异常通知？" }
$choice = [System.Windows.Forms.MessageBox]::Show(
  $message,
  "Codex 通知设置",
  [System.Windows.Forms.MessageBoxButtons]::YesNoCancel,
  [System.Windows.Forms.MessageBoxIcon]::Question
)
if ($choice -eq [System.Windows.Forms.DialogResult]::Cancel) { exit 0 }

& $DoctorScript -Repair -NoDialog | Out-Null

$settings["notifications_enabled"] = $choice -eq [System.Windows.Forms.DialogResult]::Yes
if (-not $settings.Contains("notification_quiet_hours")) {
  $settings["notification_quiet_hours"] = "22:00-08:00"
}
$json = $settings | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText($ConfigPath, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))

& $StopScript | Out-Null
& $StartScript -HostName "127.0.0.1" -Port 8767 | Out-Null
$state = if ($settings["notifications_enabled"]) { "已启用" } else { "已关闭" }
[System.Windows.Forms.MessageBox]::Show(
  "Codex 状态通知$state；静音时段为 $($settings['notification_quiet_hours'])。",
  "Codex 通知设置",
  [System.Windows.Forms.MessageBoxButtons]::OK,
  [System.Windows.Forms.MessageBoxIcon]::Information
) | Out-Null
