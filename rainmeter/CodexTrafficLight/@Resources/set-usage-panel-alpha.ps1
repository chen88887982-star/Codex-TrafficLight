param(
  [string]$Percent = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VariablesFile = Join-Path $ScriptDir "variables.inc"

if ([string]::IsNullOrWhiteSpace($Percent)) {
  Add-Type -AssemblyName Microsoft.VisualBasic
  $Percent = [Microsoft.VisualBasic.Interaction]::InputBox(
    "请输入额度面板不透明度百分比，范围 0-100。0 表示完全透明，100 表示最不透明。",
    "Codex 交通灯额度面板",
    "91"
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
$strokeAlpha = [int][Math]::Round($value * 176 / 100)
$content = Get-Content -LiteralPath $VariablesFile -Raw -Encoding Unicode

if ($content -match '(?m)^UsagePanelOpacity=.*$') {
  $content = $content -replace '(?m)^UsagePanelOpacity=.*$', "UsagePanelOpacity=$value"
} else {
  $content = $content -replace '(\[Variables\]\s*)', "`$1UsagePanelOpacity=$value`r`n"
}

if ($content -match '(?m)^UsagePanelAlpha=.*$') {
  $content = $content -replace '(?m)^UsagePanelAlpha=.*$', "UsagePanelAlpha=$alpha"
} else {
  $content = $content -replace '(\[Variables\]\s*)', "`$1UsagePanelAlpha=$alpha`r`n"
}

if ($content -match '(?m)^UsagePanelColor=.*$') {
  $content = $content -replace '(?m)^UsagePanelColor=.*$', "UsagePanelColor=12,15,20,$alpha"
} else {
  $content = $content -replace '(\[Variables\]\s*)', "`$1UsagePanelColor=12,15,20,$alpha`r`n"
}

if ($content -match '(?m)^UsagePanelStrokeAlpha=.*$') {
  $content = $content -replace '(?m)^UsagePanelStrokeAlpha=.*$', "UsagePanelStrokeAlpha=$strokeAlpha"
} else {
  $content = $content -replace '(\[Variables\]\s*)', "`$1UsagePanelStrokeAlpha=$strokeAlpha`r`n"
}

if ($content -match '(?m)^UsagePanelStrokeColor=.*$') {
  $content = $content -replace '(?m)^UsagePanelStrokeColor=.*$', "UsagePanelStrokeColor=0,210,230,$strokeAlpha"
} else {
  $content = $content -replace '(\[Variables\]\s*)', "`$1UsagePanelStrokeColor=0,210,230,$strokeAlpha`r`n"
}

Set-Content -LiteralPath $VariablesFile -Value $content -Encoding Unicode
