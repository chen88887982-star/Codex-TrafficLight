param(
  [Parameter(Mandatory=$true)]
  [ValidateSet("TextColor", "MutedTextColor", "StatusTextColor", "AccentTextColor", "ResetTextColor", "LowQuotaTextColor")]
  [string]$Variable,

  [ValidateSet("pick", "input")]
  [string]$Mode = "input"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VariablesFile = Join-Path $ScriptDir "variables.inc"
. (Join-Path $ScriptDir "skin-settings.ps1")

$labels = @{
  TextColor = "主要文字"
  MutedTextColor = "次要文字"
  StatusTextColor = "状态文字"
  AccentTextColor = "额度重点文字"
  ResetTextColor = "重置时间文字"
  LowQuotaTextColor = "低额度警告文字"
}

function Show-Error($message) {
  Add-Type -AssemblyName System.Windows.Forms
  [System.Windows.Forms.MessageBox]::Show($message, "Codex 交通灯设置") | Out-Null
}

function Clamp-Byte($value) {
  if ($value -lt 0) { return 0 }
  if ($value -gt 255) { return 255 }
  return [int]$value
}

function Read-CurrentColor($content, $name) {
  $match = [regex]::Match($content, "(?m)^$([regex]::Escape($name))=(\d+),(\d+),(\d+),(\d+)\s*$")
  if ($match.Success) {
    return @(
      [int]$match.Groups[1].Value,
      [int]$match.Groups[2].Value,
      [int]$match.Groups[3].Value,
      [int]$match.Groups[4].Value
    )
  }
  return @(235, 238, 242, 255)
}

function Convert-HexPair($value) {
  return [Convert]::ToInt32($value, 16)
}

function Parse-ColorText($raw, $fallbackAlpha) {
  $value = $raw.Trim()
  if ([string]::IsNullOrWhiteSpace($value)) {
    return $null
  }

  if ($value.StartsWith("#")) {
    $value = $value.Substring(1)
  }

  if ($value -match "^[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$") {
    $r = Convert-HexPair $value.Substring(0, 2)
    $g = Convert-HexPair $value.Substring(2, 2)
    $b = Convert-HexPair $value.Substring(4, 2)
    $a = $fallbackAlpha
    if ($value.Length -eq 8) {
      $a = Convert-HexPair $value.Substring(6, 2)
    }
    return @((Clamp-Byte $r), (Clamp-Byte $g), (Clamp-Byte $b), (Clamp-Byte $a))
  }

  $parts = $value -split "\s*,\s*"
  if ($parts.Count -eq 3 -or $parts.Count -eq 4) {
    $numbers = @()
    foreach ($part in $parts) {
      $number = 0
      if (-not [int]::TryParse($part, [ref]$number)) {
        throw "请输入 #RRGGBB、#RRGGBBAA、R,G,B 或 R,G,B,A。"
      }
      $numbers += (Clamp-Byte $number)
    }
    if ($numbers.Count -eq 3) {
      $numbers += (Clamp-Byte $fallbackAlpha)
    }
    return $numbers
  }

  throw "请输入 #RRGGBB、#RRGGBBAA、R,G,B 或 R,G,B,A。"
}

function Write-Variable($content, $name, $rgba) {
  $line = "$name=$($rgba[0]),$($rgba[1]),$($rgba[2]),$($rgba[3])"
  if ($content -match "(?m)^$([regex]::Escape($name))=.*$") {
    return $content -replace "(?m)^$([regex]::Escape($name))=.*$", $line
  }
  return $content -replace "(\[Variables\]\s*)", "`$1$line`r`n"
}

$content = Get-Content -LiteralPath $VariablesFile -Raw -Encoding Unicode
$current = Read-CurrentColor $content $Variable
$label = $labels[$Variable]
$rgba = $null

if ($Mode -eq "pick") {
  Add-Type -AssemblyName System.Windows.Forms
  Add-Type -AssemblyName System.Drawing

  $dialog = New-Object System.Windows.Forms.ColorDialog
  $dialog.FullOpen = $true
  $dialog.Color = [System.Drawing.Color]::FromArgb($current[0], $current[1], $current[2])

  if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
    exit 0
  }

  Add-Type -AssemblyName Microsoft.VisualBasic
  $defaultOpacity = [int][Math]::Round($current[3] * 100 / 255)
  $opacityText = [Microsoft.VisualBasic.Interaction]::InputBox(
    "请输入 $label 透明度百分比，范围 0-100。",
    "Codex 交通灯文字透明度",
    "$defaultOpacity"
  )

  if ([string]::IsNullOrWhiteSpace($opacityText)) {
    exit 0
  }

  $opacity = 0
  if (-not [int]::TryParse($opacityText, [ref]$opacity)) {
    Show-Error "请输入 0-100 之间的整数。"
    exit 1
  }
  if ($opacity -lt 0) { $opacity = 0 }
  if ($opacity -gt 100) { $opacity = 100 }

  $alpha = [int][Math]::Round($opacity * 255 / 100)
  $rgba = @($dialog.Color.R, $dialog.Color.G, $dialog.Color.B, $alpha)
} else {
  Add-Type -AssemblyName Microsoft.VisualBasic
  $defaultColor = "$($current[0]),$($current[1]),$($current[2]),$($current[3])"
  $rawColor = [Microsoft.VisualBasic.Interaction]::InputBox(
    "请输入 $label 颜色。支持 #RRGGBB、#RRGGBBAA、R,G,B 或 R,G,B,A。",
    "Codex 交通灯文字颜色",
    $defaultColor
  )

  if ([string]::IsNullOrWhiteSpace($rawColor)) {
    exit 0
  }

  try {
    $rgba = Parse-ColorText $rawColor $current[3]
  } catch {
    Show-Error $_.Exception.Message
    exit 1
  }
}

$content = Write-Variable $content $Variable $rgba
Set-Content -LiteralPath $VariablesFile -Value $content -Encoding Unicode
Refresh-CodexSkins
