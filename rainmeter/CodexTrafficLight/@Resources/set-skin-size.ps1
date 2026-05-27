param(
  [string]$Size = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VariablesFile = Join-Path $ScriptDir "variables.inc"

if ([string]::IsNullOrWhiteSpace($Size)) {
  Add-Type -AssemblyName Microsoft.VisualBasic
  $Size = [Microsoft.VisualBasic.Interaction]::InputBox(
    "请输入皮肤整体尺寸，格式为 宽度,高度。例如：208,462。",
    "Codex 交通灯皮肤尺寸",
    "208,462"
  )
}

if ([string]::IsNullOrWhiteSpace($Size)) {
  exit 0
}

$parts = $Size -split '[,，xX*＊ ]+' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
if ($parts.Count -ne 2) {
  Add-Type -AssemblyName System.Windows.Forms
  [System.Windows.Forms.MessageBox]::Show("请输入两个整数，格式为 宽度,高度。", "Codex 交通灯设置") | Out-Null
  exit 1
}

$width = 0
$height = 0
if (-not [int]::TryParse($parts[0], [ref]$width) -or -not [int]::TryParse($parts[1], [ref]$height)) {
  Add-Type -AssemblyName System.Windows.Forms
  [System.Windows.Forms.MessageBox]::Show("宽度和高度都必须是整数。", "Codex 交通灯设置") | Out-Null
  exit 1
}

if ($width -lt 160) {
  $width = 160
}
if ($width -gt 420) {
  $width = 420
}
if ($height -lt 360) {
  $height = 360
}
if ($height -gt 760) {
  $height = 760
}

$content = Get-Content -LiteralPath $VariablesFile -Raw -Encoding Unicode

if ($content -match '(?m)^SkinWidth=.*$') {
  $content = $content -replace '(?m)^SkinWidth=.*$', "SkinWidth=$width"
} else {
  $content = $content -replace '(\[Variables\]\s*)', "`$1SkinWidth=$width`r`n"
}

if ($content -match '(?m)^SkinHeight=.*$') {
  $content = $content -replace '(?m)^SkinHeight=.*$', "SkinHeight=$height"
} else {
  $content = $content -replace '(\[Variables\]\s*)', "`$1SkinHeight=$height`r`n"
}

Set-Content -LiteralPath $VariablesFile -Value $content -Encoding Unicode
