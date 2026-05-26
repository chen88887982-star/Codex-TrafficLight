param(
  [string]$Url = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VariablesFile = Join-Path $ScriptDir "variables.inc"

if ([string]::IsNullOrWhiteSpace($Url)) {
  Add-Type -AssemblyName Microsoft.VisualBasic
  $Url = [Microsoft.VisualBasic.Interaction]::InputBox(
    "请输入完整状态接口地址，例如 http://192.168.2.112:8765/status",
    "Codex 交通灯状态接口",
    "http://192.168.2.112:8765/status"
  )
}

if ([string]::IsNullOrWhiteSpace($Url)) {
  exit 0
}

if ($Url -notmatch '^https?://') {
  Add-Type -AssemblyName System.Windows.Forms
  [System.Windows.Forms.MessageBox]::Show("地址必须以 http:// 或 https:// 开头。", "Codex 交通灯设置") | Out-Null
  exit 1
}

$content = Get-Content -LiteralPath $VariablesFile -Raw -Encoding Unicode
if ($content -match '(?m)^StatusUrl=.*$') {
  $content = $content -replace '(?m)^StatusUrl=.*$', "StatusUrl=$Url"
} else {
  $content = $content -replace '(\[Variables\]\s*)', "`$1StatusUrl=$Url`r`n"
}

Set-Content -LiteralPath $VariablesFile -Value $content -Encoding Unicode

