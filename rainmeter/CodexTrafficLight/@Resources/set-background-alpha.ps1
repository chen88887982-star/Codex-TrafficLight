param(
  [string]$Percent = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VariablesFile = Join-Path $ScriptDir "variables.inc"

if ([string]::IsNullOrWhiteSpace($Percent)) {
  Add-Type -AssemblyName Microsoft.VisualBasic
  $Percent = [Microsoft.VisualBasic.Interaction]::InputBox(
    "请输入玻璃背景不透明度百分比，范围 0-100。0 表示完全透明，100 表示最不透明。",
    "Codex 交通灯玻璃背景",
    "55"
  )
}

if ([string]::IsNullOrWhiteSpace($Percent)) {
  exit 0
}

$value = 0
if (-not [int]::TryParse($Percent, [ref]$value)) {
  Add-Type -AssemblyName System.Windows.Forms
  [System.Windows.Forms.MessageBox]::Show("请输入 0-100 之间的整数。", "Codex 交通灯设置") | Out-Null
  exit 1
}

if ($value -lt 0) {
  $value = 0
}
if ($value -gt 100) {
  $value = 100
}

$alpha = [int][Math]::Round($value * 255 / 100)
$strokeAlpha = [int][Math]::Round($value * 240 / 100)
$highlightAlpha = [int][Math]::Round($value * 32 / 100)
$content = Get-Content -LiteralPath $VariablesFile -Raw -Encoding Unicode

if ($content -match '(?m)^BackgroundOpacity=.*$') {
  $content = $content -replace '(?m)^BackgroundOpacity=.*$', "BackgroundOpacity=$value"
} else {
  $content = $content -replace '(\[Variables\]\s*)', "`$1BackgroundOpacity=$value`r`n"
}

if ($content -match '(?m)^BackgroundAlpha=.*$') {
  $content = $content -replace '(?m)^BackgroundAlpha=.*$', "BackgroundAlpha=$alpha"
} else {
  $content = $content -replace '(\[Variables\]\s*)', "`$1BackgroundAlpha=$alpha`r`n"
}

if ($content -match '(?m)^BackgroundColor=.*$') {
  $content = $content -replace '(?m)^BackgroundColor=.*$', "BackgroundColor=18,28,34,$alpha"
} else {
  $content = $content -replace '(\[Variables\]\s*)', "`$1BackgroundColor=18,28,34,$alpha`r`n"
}

if ($content -match '(?m)^PanelStrokeAlpha=.*$') {
  $content = $content -replace '(?m)^PanelStrokeAlpha=.*$', "PanelStrokeAlpha=$strokeAlpha"
} else {
  $content = $content -replace '(\[Variables\]\s*)', "`$1PanelStrokeAlpha=$strokeAlpha`r`n"
}

if ($content -match '(?m)^PanelStrokeColor=.*$') {
  $content = $content -replace '(?m)^PanelStrokeColor=.*$', "PanelStrokeColor=120,210,230,$strokeAlpha"
} else {
  $content = $content -replace '(\[Variables\]\s*)', "`$1PanelStrokeColor=120,210,230,$strokeAlpha`r`n"
}

if ($content -match '(?m)^BackgroundHighlightAlpha=.*$') {
  $content = $content -replace '(?m)^BackgroundHighlightAlpha=.*$', "BackgroundHighlightAlpha=$highlightAlpha"
} else {
  $content = $content -replace '(\[Variables\]\s*)', "`$1BackgroundHighlightAlpha=$highlightAlpha`r`n"
}

if ($content -match '(?m)^BackgroundHighlightColor=.*$') {
  $content = $content -replace '(?m)^BackgroundHighlightColor=.*$', "BackgroundHighlightColor=160,230,255,$highlightAlpha"
} else {
  $content = $content -replace '(\[Variables\]\s*)', "`$1BackgroundHighlightColor=160,230,255,$highlightAlpha`r`n"
}

Set-Content -LiteralPath $VariablesFile -Value $content -Encoding Unicode


