param([string]$Size = '')
$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $ScriptDir 'skin-settings.ps1')
$VariablesFile = Join-Path $ScriptDir 'variables.inc'
$content = Get-Content -LiteralPath $VariablesFile -Raw -Encoding Unicode
$scaleMatch = [regex]::Match($content, '(?m)^SkinScale=([0-9.]+)')
$current = if ($scaleMatch.Success) { [double]::Parse($scaleMatch.Groups[1].Value, [Globalization.CultureInfo]::InvariantCulture) * 100 } else { 100 }
if ([string]::IsNullOrWhiteSpace($Size)) {
  Add-Type -AssemblyName Microsoft.VisualBasic
  $Size = [Microsoft.VisualBasic.Interaction]::InputBox('请输入整体缩放百分比，范围 75-180。所有文字、图形与点击区域同比例调整。也支持旧格式 宽度,高度。', 'Codex 交通灯整体缩放', [string]$current)
}
if ([string]::IsNullOrWhiteSpace($Size)) { exit 0 }
$parts = $Size.Trim().TrimEnd('%') -split '[,，xX*＊ ]+'
$parsed = 0.0
try {
  if ($parts.Count -eq 2) {
    $scale = [Math]::Min([double]::Parse($parts[0], [Globalization.CultureInfo]::InvariantCulture) / 208, [double]::Parse($parts[1], [Globalization.CultureInfo]::InvariantCulture) / 736)
  } elseif ($parts.Count -eq 1) {
    $scale = [double]::Parse($parts[0], [Globalization.CultureInfo]::InvariantCulture) / 100
  } else { throw 'Invalid size' }
  if ([double]::IsNaN($scale) -or [double]::IsInfinity($scale)) { throw 'Invalid size' }
} catch {
  Add-Type -AssemblyName System.Windows.Forms
  [System.Windows.Forms.MessageBox]::Show('请输入 75-180 之间的缩放百分比，或两个有效尺寸。', 'Codex 交通灯设置') | Out-Null
  exit 1
}
$scale = [Math]::Round([Math]::Max(0.75, [Math]::Min(1.8, $scale)), 3)
$content = Set-SkinVariable $content 'SkinScale' $scale.ToString([Globalization.CultureInfo]::InvariantCulture)
$content = Set-SkinVariable $content 'SkinWidth' ([string][int][Math]::Round(208 * $scale))
$content = Set-SkinVariable $content 'SkinHeight' ([string][int][Math]::Round(736 * $scale))
Set-Content -LiteralPath $VariablesFile -Value $content -Encoding Unicode
Refresh-CodexSkins
