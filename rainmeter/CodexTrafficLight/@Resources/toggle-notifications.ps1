param([string]$ServiceRoot, [string]$StatusUrl = '')

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms

if ([string]::IsNullOrWhiteSpace($ServiceRoot) -or -not (Test-Path -LiteralPath $ServiceRoot -PathType Container)) {
  [System.Windows.Forms.MessageBox]::Show(
    "未找到状态服务项目目录。请重新运行 install-rainmeter-skin.cmd 后再试。",
    "Codex 本机通知设置",
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Warning
  ) | Out-Null
  exit 1
}

if ($StatusUrl -and -not ([Uri]$StatusUrl).IsLoopback) {
  [System.Windows.Forms.MessageBox]::Show('当前显示远程电脑，通知需要在服务所在电脑设置。本机设置不会控制 Mac 或其他 Windows 服务。请打开对应状态看板查看目标。', 'Codex 通知目标：远程服务', 'OK', 'Information') | Out-Null
  exit 0
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

$ServiceDir = Join-Path $ProjectRoot 'win\codex_status_server'
. (Join-Path $ServiceDir '.internal\service-settings.ps1')
$launchSettings = Get-ServiceLaunchSettings $ServiceDir
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
$message = if ($enabled) { "本机 $($launchSettings.HostName):$($launchSettings.Port) 当前通知已启用。是否继续保持启用？选择否将关闭。" } else { "本机 $($launchSettings.HostName):$($launchSettings.Port) 当前通知未启用。是否启用等待确认、完成和异常通知？" }
$choice = [System.Windows.Forms.MessageBox]::Show(
  $message,
  "Codex 本机通知设置",
  [System.Windows.Forms.MessageBoxButtons]::YesNoCancel,
  [System.Windows.Forms.MessageBoxIcon]::Question
)
if ($choice -eq [System.Windows.Forms.DialogResult]::Cancel) { exit 0 }

# Notification settings are independent of legacy migration and log cleanup.
# Preserve the service's original listening address and port across this restart.

$settings["notifications_enabled"] = $choice -eq [System.Windows.Forms.DialogResult]::Yes
if (-not $settings.Contains("notification_quiet_hours")) {
  $settings["notification_quiet_hours"] = "22:00-08:00"
}
$json = $settings | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText($ConfigPath, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))

try {
  & $StopScript | Out-Null
  & $StartScript -HostName $launchSettings.HostName -Port $launchSettings.Port | Out-Null
} catch {
  [System.Windows.Forms.MessageBox]::Show("通知设置已保存，但服务重启失败：$($_.Exception.Message)。请运行只读体检查看原因。", 'Codex 本机通知设置', 'OK', 'Warning') | Out-Null
  exit 1
}
$state = if ($settings["notifications_enabled"]) { "已启用" } else { "已关闭" }
[System.Windows.Forms.MessageBox]::Show(
  "Codex 状态通知$state；静音时段为 $($settings['notification_quiet_hours'])。",
  "Codex 本机通知设置",
  [System.Windows.Forms.MessageBoxButtons]::OK,
  [System.Windows.Forms.MessageBoxIcon]::Information
) | Out-Null
