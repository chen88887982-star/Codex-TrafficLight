param(
  [string]$Url = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VariablesFile = Join-Path $ScriptDir "variables.inc"

if ([string]::IsNullOrWhiteSpace($Url)) {
  Add-Type -AssemblyName Microsoft.VisualBasic
  $Url = [Microsoft.VisualBasic.Interaction]::InputBox(
    "请输入完整状态接口地址。本机用 http://127.0.0.1:8765/rainmeter；跨电脑用 http://对方IP:8765/rainmeter。",
    "Codex 交通灯状态接口",
    "http://127.0.0.1:8765/rainmeter"
  )
}

if ([string]::IsNullOrWhiteSpace($Url)) {
  exit 0
}

try {
  $uri = [Uri]$Url
} catch {
  $uri = $null
}

if ($null -eq $uri -or -not $uri.IsAbsoluteUri -or $uri.Scheme -notin @("http", "https")) {
  Add-Type -AssemblyName System.Windows.Forms
  [System.Windows.Forms.MessageBox]::Show("地址必须以 http:// 或 https:// 开头。", "Codex 交通灯设置") | Out-Null
  exit 1
}

$builder = [UriBuilder]$uri
$normalizedPath = $builder.Path.TrimEnd("/")
if ($normalizedPath.EndsWith("/rainmeter", [StringComparison]::OrdinalIgnoreCase)) {
  $builder.Path = $normalizedPath.Substring(0, $normalizedPath.Length - "/rainmeter".Length) + "/status"
}
$JsonUrl = $builder.Uri.AbsoluteUri

$content = Get-Content -LiteralPath $VariablesFile -Raw -Encoding Unicode
if ($content -match '(?m)^StatusUrl=.*$') {
  $content = [regex]::Replace($content, '(?m)^StatusUrl=.*$', { param($match) "StatusUrl=$Url" })
} else {
  $content = $content -replace '(\[Variables\]\s*)', "`$1StatusUrl=$Url`r`n"
}

if ($content -match '(?m)^JsonStatusUrl=.*$') {
  $content = [regex]::Replace($content, '(?m)^JsonStatusUrl=.*$', { param($match) "JsonStatusUrl=$JsonUrl" })
} else {
  $content = $content -replace '(\[Variables\]\s*)', "`$1JsonStatusUrl=$JsonUrl`r`n"
}

Set-Content -LiteralPath $VariablesFile -Value $content -Encoding Unicode


