param(
  [string]$HostName = "0.0.0.0",
  [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StatusFile = Join-Path $ScriptDir "status.json"

if (-not (Test-Path -LiteralPath $StatusFile)) {
  & (Join-Path $ScriptDir "set-status.ps1") idle | Out-Null
}

if ($HostName -eq "0.0.0.0") {
  $address = [System.Net.IPAddress]::Any
} else {
  $address = [System.Net.IPAddress]::Parse($HostName)
}

$listener = [System.Net.Sockets.TcpListener]::new($address, $Port)

try {
  $listener.Start()
} catch {
  Write-Host "状态服务启动失败：$($_.Exception.Message)" -ForegroundColor Red
  Write-Host "如果端口被占用，请关闭占用程序，或改用其它端口。"
  pause
  exit 1
}

Write-Host "Codex status server is running."
Write-Host "Same Windows: http://127.0.0.1:$Port/status"
Write-Host "Other computer: http://THIS-WINDOWS-IP:$Port/status"
Write-Host "Status file: $StatusFile"
Write-Host "按 Ctrl+C 或关闭窗口停止服务。"

try {
  while ($true) {
    $client = $listener.AcceptTcpClient()

    try {
      $stream = $client.GetStream()
      $reader = [System.IO.StreamReader]::new($stream, [Text.Encoding]::ASCII, $false, 1024, $true)
      $requestLine = $reader.ReadLine()

      while ($reader.Peek() -gt -1) {
        $line = $reader.ReadLine()
        if ([string]::IsNullOrEmpty($line)) {
          break
        }
      }

      if ($requestLine -match "^GET\s+/status/?\s+HTTP/") {
        try {
          $json = Get-Content -LiteralPath $StatusFile -Raw -Encoding UTF8
          $null = $json | ConvertFrom-Json
        } catch {
          $json = '{"status":"error","message":"status.json 读取失败","updated_at":""}'
        }

        $body = [Text.Encoding]::UTF8.GetBytes($json)
        $headers = "HTTP/1.1 200 OK`r`nContent-Type: application/json; charset=utf-8`r`nCache-Control: no-store`r`nAccess-Control-Allow-Origin: *`r`nContent-Length: $($body.Length)`r`nConnection: close`r`n`r`n"
      } else {
        $body = [Text.Encoding]::UTF8.GetBytes("Not Found")
        $headers = "HTTP/1.1 404 Not Found`r`nContent-Type: text/plain; charset=utf-8`r`nContent-Length: $($body.Length)`r`nConnection: close`r`n`r`n"
      }

      $headerBytes = [Text.Encoding]::ASCII.GetBytes($headers)
      $stream.Write($headerBytes, 0, $headerBytes.Length)
      $stream.Write($body, 0, $body.Length)
    } finally {
      $client.Close()
    }
  }
} finally {
  $listener.Stop()
}

