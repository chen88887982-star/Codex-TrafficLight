$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VariablesFile = Join-Path $ScriptDir "variables.inc"
. (Join-Path $ScriptDir "skin-settings.ps1")

$content = Get-Content -LiteralPath $VariablesFile -Raw -Encoding Unicode

if ($content -match '(?m)^IdleChaseEnabled=1\s*$') {
  $content = $content -replace '(?m)^IdleChaseEnabled=.*$', 'IdleChaseEnabled=0'
} elseif ($content -match '(?m)^IdleChaseEnabled=') {
  $content = $content -replace '(?m)^IdleChaseEnabled=.*$', 'IdleChaseEnabled=1'
} else {
  $content = $content -replace '(\[Variables\]\s*)', "`$1IdleChaseEnabled=1`r`n"
}

Set-Content -LiteralPath $VariablesFile -Value $content -Encoding Unicode
Refresh-CodexSkins
