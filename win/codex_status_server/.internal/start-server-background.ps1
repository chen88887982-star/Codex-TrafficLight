param(
  [string]$HostName = "127.0.0.1",
  [int]$Port = 8767,
  [int]$StartupTimeoutSeconds = 20
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ServiceDir = Split-Path -Parent $ScriptDir
$ProjectRoot = (Resolve-Path (Join-Path $ServiceDir "..\..")).Path
. (Join-Path $ScriptDir 'service-settings.ps1')
$savedSettings = Get-ServiceLaunchSettings $ServiceDir
if (-not $PSBoundParameters.ContainsKey('HostName')) { $HostName = $savedSettings.HostName }
if (-not $PSBoundParameters.ContainsKey('Port')) { $Port = $savedSettings.Port }
if ($env:CODEX_STATUS_HOST) { $HostName = $env:CODEX_STATUS_HOST }
if ($env:CODEX_STATUS_PORT) { $Port = [int]$env:CODEX_STATUS_PORT }
if ($Port -lt 1 -or $Port -gt 65535 -or $HostName -notmatch '^[a-zA-Z0-9.:_-]+$') { throw 'Invalid HostName or Port.' }
$RuntimeDir = Join-Path $ServiceDir ".runtime"
$ServerFile = Join-Path $ScriptDir "server.py"
$StdoutFile = Join-Path $RuntimeDir "status-server-output.log"
$StderrFile = Join-Path $RuntimeDir "status-server-error.log"
$HealthUri = "http://127.0.0.1:$Port/health"
$ExpectedService = "codex-traffic-light-status"

New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
$runtimeItem = Get-Item -LiteralPath $RuntimeDir -Force
$runtimeItem.Attributes = $runtimeItem.Attributes -bor [System.IO.FileAttributes]::Hidden

function Move-LegacyRuntimeFiles {
  $legacyFiles = @(
    Get-ChildItem -LiteralPath $ServiceDir -File -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -match "^(status\.json|usage-cache\.json|status-server\.(?:log(?:\.\d+)?|pid)|status-server-(?:output|error)\.log)$" }
  )
  if (-not $legacyFiles) { return }
  $archiveDir = Join-Path $RuntimeDir ("legacy-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
  foreach ($legacy in $legacyFiles) {
    $target = Join-Path $RuntimeDir $legacy.Name
    try {
      if (-not (Test-Path -LiteralPath $target) -and $legacy.Name -notmatch "^status-server\.log\.\d+$") {
        Move-Item -LiteralPath $legacy.FullName -Destination $target
        continue
      }
      New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null
      Move-Item -LiteralPath $legacy.FullName -Destination (Join-Path $archiveDir $legacy.Name)
    } catch {
      Write-Warning "旧运行文件暂未迁移：$($legacy.FullName)；$($_.Exception.Message)"
    }
  }
}

Move-LegacyRuntimeFiles

function Get-StatusHealth {
  try {
    $health = Invoke-RestMethod -Uri $HealthUri -TimeoutSec 2
    if (
      $health.service -eq $ExpectedService -and
      $health.service_version -eq "0.5.0" -and
      [int]$health.protocol_version -eq 2 -and
      $health.status -in @("ok", "degraded", "error")
    ) {
      return $health
    }
  } catch {
  }
  return $null
}

$health = Get-StatusHealth
if ($null -ne $health -and $PSBoundParameters.ContainsKey('HostName')) {
  $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($listener -and $listener.LocalAddress -ne $HostName) {
    & (Join-Path $ScriptDir 'stop-server.ps1') | Out-Null
    $health = Get-StatusHealth
  }
}
if ($null -ne $health) {
  Write-Output "[OK] $Port 状态服务已在运行，未重复启动。"
  exit 0
}

$occupied = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($null -ne $occupied) {
  Write-Error "端口 $Port 已被其他程序占用，且未返回预期的状态服务健康信息。"
  exit 1
}

$pythonCandidates = @(
  (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
  (Join-Path $env:LocalAppData "Programs\Python\Python314\python.exe"),
  (Join-Path $env:LocalAppData "Programs\Python\Python313\python.exe"),
  (Join-Path $env:LocalAppData "Programs\Python\Python312\python.exe")
)
$PythonExe = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $PythonExe) {
  $command = Get-Command python -ErrorAction SilentlyContinue
  if ($command) { $PythonExe = $command.Source }
}
if (-not $PythonExe) {
  Write-Error "未找到可用的 Python。请先恢复项目 .venv 或安装 Python 3。"
  exit 1
}

$env:HOST = $HostName
$env:PORT = [string]$Port
$process = Start-Process -FilePath $PythonExe -ArgumentList @('"' + $ServerFile + '"') -WorkingDirectory $ScriptDir `
  -WindowStyle Hidden -RedirectStandardOutput $StdoutFile -RedirectStandardError $StderrFile -PassThru

$deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
do {
  Start-Sleep -Milliseconds 400
  $health = Get-StatusHealth
  if ($null -ne $health) {
    $servicePid = $process.Id
    try {
      $pidRecord = Get-Content -LiteralPath (Join-Path $RuntimeDir "status-server.pid") -Raw -Encoding UTF8 | ConvertFrom-Json
      $servicePid = [int]$pidRecord.pid
    } catch {
    }
    Save-ServiceLaunchSettings $ServiceDir $HostName $Port
    Write-Output "[OK] $Port 状态服务已隐藏运行，PID=$servicePid，健康状态=$($health.status)。"
    exit 0
  }
  if ($process.HasExited) {
    Write-Error "状态服务启动后立即退出（退出码 $($process.ExitCode)）。请检查 $StderrFile。"
    exit 1
  }
} while ((Get-Date) -lt $deadline)

Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
Write-Error "状态服务在 $StartupTimeoutSeconds 秒内未通过健康检查，已停止启动进程。"
exit 1
