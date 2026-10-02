# Shared helpers; dot-source this file after defining $ScriptDir.
function Refresh-CodexSkins {
  $running = Get-Process -Name Rainmeter -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($running -and $running.Path -and (Test-Path -LiteralPath $running.Path)) {
    & $running.Path '!RefreshApp'
  }
}

function Set-SkinVariable([string]$Content, [string]$Name, [string]$Value) {
  $pattern = '(?m)^' + [regex]::Escape($Name) + '=.*$'
  if ($Content -match $pattern) {
    return [regex]::Replace($Content, $pattern, { param($m) "$Name=$Value" })
  }
  return $Content.TrimEnd() + [Environment]::NewLine + "$Name=$Value" + [Environment]::NewLine
}
