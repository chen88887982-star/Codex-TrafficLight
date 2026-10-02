function Get-ServiceLaunchSettings([string]$ServiceDir) {
  $settings = @{ HostName = '127.0.0.1'; Port = 8767 }
  $path = Join-Path $ServiceDir '.runtime\launch-settings.json'
  if (Test-Path -LiteralPath $path) {
    try {
      $saved = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
      if ($saved.host -is [string] -and $saved.host -match '^[a-zA-Z0-9.:_-]+$') { $settings.HostName = $saved.host }
      if ([int]$saved.port -ge 1 -and [int]$saved.port -le 65535) { $settings.Port = [int]$saved.port }
    } catch { Write-Warning 'Saved launch settings are invalid; using local defaults.' }
  }
  if (-not (Test-Path -LiteralPath $path)) {
    # Upgrade existing services without changing their binding before the first saved launch.
    $pidPath = Join-Path $ServiceDir '.runtime\status-server.pid'
    try {
      if (Test-Path -LiteralPath $pidPath) {
        $record = Get-Content -LiteralPath $pidPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $listener = Get-NetTCPConnection -LocalPort ([int]$record.port) -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -eq [int]$record.pid } | Select-Object -First 1
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$record.pid)" -ErrorAction SilentlyContinue
        $expected = [regex]::Escape((Join-Path $ServiceDir '.internal\server.py'))
        if ($listener -and $process.CommandLine -match $expected) {
          $settings.HostName = $listener.LocalAddress
          $settings.Port = [int]$record.port
        }
      }
    } catch { Write-Warning 'The previous listening settings could not be recovered.' }
  }
  return $settings
}

function Save-ServiceLaunchSettings([string]$ServiceDir, [string]$HostName, [int]$Port) {
  $path = Join-Path $ServiceDir '.runtime\launch-settings.json'
  $temporary = $path + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
  $json = @{ host = $HostName; port = $Port } | ConvertTo-Json
  try {
    [IO.File]::WriteAllText($temporary, $json, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $path -Force
  } finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
  }
}
