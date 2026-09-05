param([switch]$Repair, [switch]$NoDialog)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ServiceDir = Split-Path -Parent $ScriptDir
$ProjectRoot = (Resolve-Path (Join-Path $ServiceDir "..\..")).Path
$RuntimeDir = Join-Path $ServiceDir ".runtime"
$ExpectedPort = 8767
$LegacyPort = 8765
$ExpectedService = "codex-traffic-light-status"
$ExpectedVersion = "0.4.0"
$ExpectedProtocol = 2
$StartScript = Join-Path $ScriptDir "start-server-background.ps1"
$InstalledVariables = Join-Path $env:USERPROFILE "Documents\Rainmeter\Skins\CodexTrafficLight\@Resources\variables.inc"

function Get-StatusHealth([int]$Port) {
  try {
    return Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 3
  } catch {
    return $null
  }
}

function Get-Listener([int]$Port) {
  return Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
}

function Test-ProjectStatusProcess([int]$ProcessId) {
  $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
  if ($null -eq $process -or [string]::IsNullOrWhiteSpace($process.CommandLine)) { return $false }
  $rootPattern = [regex]::Escape($ProjectRoot)
  return $process.CommandLine -match $rootPattern -and $process.CommandLine -match "codex_status_server"
}

function Update-InstalledDefaults {
  if (-not (Test-Path -LiteralPath $InstalledVariables)) { return "未找到已安装的 variables.inc" }
  $content = [IO.File]::ReadAllText($InstalledVariables, [Text.Encoding]::Unicode)
  $updated = $content.Replace("http://127.0.0.1:8765/rainmeter", "http://127.0.0.1:8767/rainmeter")
  $updated = $updated.Replace("http://127.0.0.1:8765/status", "http://127.0.0.1:8767/status")
  if ($updated -notmatch "(?m)^TasksUrl=") {
    $updated = $updated.Replace(
      "JsonStatusUrl=http://127.0.0.1:8767/status",
      "JsonStatusUrl=http://127.0.0.1:8767/status`r`nTasksUrl=http://127.0.0.1:8767/tasks"
    )
  }
  if ($updated -ne $content) {
    [IO.File]::WriteAllText($InstalledVariables, $updated, [Text.Encoding]::Unicode)
    return "已升级 Rainmeter 本机默认地址"
  }
  return "Rainmeter 地址无需修改"
}

function Remove-OversizedLegacyLogs {
  $removed = 0
  foreach ($directory in @($ServiceDir, $RuntimeDir)) {
    if (-not (Test-Path -LiteralPath $directory)) { continue }
    $resolvedDirectory = [IO.Path]::GetFullPath($directory)
    foreach ($log in Get-ChildItem -LiteralPath $directory -Recurse -File -Filter "status-server.log.*" -ErrorAction SilentlyContinue) {
      $resolvedLog = [IO.Path]::GetFullPath($log.FullName)
      if (-not $resolvedLog.StartsWith($resolvedDirectory + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        continue
      }
      if ($log.Length -gt 50MB) {
        Remove-Item -LiteralPath $resolvedLog -Force
        $removed++
      }
    }
  }
  return $removed
}

$expectedHealth = Get-StatusHealth $ExpectedPort
$legacyHealth = Get-StatusHealth $LegacyPort
$legacyFiles = @(
  Get-ChildItem -LiteralPath $ServiceDir -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match "^(status|usage-cache|status-server).*" }
)
$report = [System.Collections.Generic.List[string]]::new()
$report.Add("CodexTrafficLight 服务体检")
$report.Add("项目：$ProjectRoot")
$report.Add("8767：$(if ($expectedHealth) { "$($expectedHealth.status) / v$($expectedHealth.service_version) / p$($expectedHealth.protocol_version)" } else { "未运行" })")
$report.Add("8765：$(if ($legacyHealth) { "$($legacyHealth.service) / 旧服务仍在运行" } else { "未运行" })")
$report.Add("根目录旧运行文件：$($legacyFiles.Count)")

if ($Repair) {
  if ($legacyHealth -and $legacyHealth.service -eq $ExpectedService) {
    $listener = Get-Listener $LegacyPort
    if ($null -ne $listener -and (Test-ProjectStatusProcess $listener.OwningProcess)) {
      Stop-Process -Id $listener.OwningProcess -Force
      $report.Add("已停止本项目旧 8765 服务 PID=$($listener.OwningProcess)")
    } else {
      throw "8765 返回预期服务，但无法安全确认进程属于当前项目；未停止任何进程。"
    }
  }

  $expectedHealth = Get-StatusHealth $ExpectedPort
  if ($expectedHealth -and (
      $expectedHealth.service_version -ne $ExpectedVersion -or
      [int]$expectedHealth.protocol_version -ne $ExpectedProtocol
    )) {
    $listener = Get-Listener $ExpectedPort
    if ($null -ne $listener -and (Test-ProjectStatusProcess $listener.OwningProcess)) {
      Stop-Process -Id $listener.OwningProcess -Force
      $expectedHealth = $null
      $report.Add("已停止本项目旧版本 8767 服务 PID=$($listener.OwningProcess)")
    } else {
      throw "8767 返回旧版服务，但无法安全确认进程属于当前项目；未停止任何进程。"
    }
  }

  $report.Add((Update-InstalledDefaults))
  & $StartScript -HostName "127.0.0.1" -Port $ExpectedPort | ForEach-Object { $report.Add([string]$_) }
  $removedLogs = Remove-OversizedLegacyLogs
  if ($removedLogs) { $report.Add("已清理 $removedLogs 个超过 50 MB 的旧轮转日志") }

  $expectedHealth = Get-StatusHealth $ExpectedPort
  if (-not $expectedHealth -or $expectedHealth.service -ne $ExpectedService) {
    throw "修复后 8767 服务仍未通过身份检查。"
  }
  $report.Add("修复完成：8767 v$($expectedHealth.service_version)，协议 $($expectedHealth.protocol_version)")
}

$reportText = $report -join [Environment]::NewLine
Write-Output $reportText
if (-not $NoDialog) {
  try {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
      $reportText,
      "CodexTrafficLight 服务体检",
      [System.Windows.Forms.MessageBoxButtons]::OK,
      [System.Windows.Forms.MessageBoxIcon]::Information
    ) | Out-Null
  } catch {
  }
}
