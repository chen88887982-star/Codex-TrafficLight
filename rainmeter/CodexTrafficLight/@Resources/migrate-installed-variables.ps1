param(
  [Parameter(Mandatory = $true)][string]$VariablesPath,
  [Parameter(Mandatory = $true)][string]$ServiceRoot
)

$ErrorActionPreference = "Stop"
$resolvedVariables = [IO.Path]::GetFullPath($VariablesPath)
$resolvedRoot = [IO.Path]::GetFullPath($ServiceRoot).TrimEnd([IO.Path]::DirectorySeparatorChar)
if (-not (Test-Path -LiteralPath $resolvedVariables -PathType Leaf)) {
  throw "variables.inc 不存在：$resolvedVariables"
}
if (-not (Test-Path -LiteralPath $resolvedRoot -PathType Container)) {
  throw "项目目录不存在：$resolvedRoot"
}

$content = [IO.File]::ReadAllText($resolvedVariables, [Text.Encoding]::Unicode)
$content = $content.Replace("http://127.0.0.1:8765/rainmeter", "http://127.0.0.1:8767/rainmeter")
$content = $content.Replace("http://127.0.0.1:8765/status", "http://127.0.0.1:8767/status")
$content = [regex]::Replace($content, "(?m)^SkinHeight=(568|716)\s*$", "SkinHeight=736")

$statusMatch = [regex]::Match($content, "(?m)^StatusUrl=([^\r\n]+)")
$tasksUrl = if ($statusMatch.Success) {
  $statusMatch.Groups[1].Value -replace "/rainmeter(?=\?|$)", "/tasks"
} else {
  "http://127.0.0.1:8767/tasks"
}

if ($content -match "(?m)^TasksUrl=") {
  # Preserve customized remote endpoints; only upgrade the known legacy local URL.
  $content = $content.Replace('http://127.0.0.1:8765/tasks', 'http://127.0.0.1:8767/tasks')
} else {
  $content = $content.TrimEnd() + [Environment]::NewLine + "TasksUrl=$tasksUrl" + [Environment]::NewLine
}
if ($content -match "(?m)^ServiceRoot=") {
  $content = [regex]::Replace($content, "(?m)^ServiceRoot=.*$", "ServiceRoot=$resolvedRoot")
} else {
  $content = $content.TrimEnd() + [Environment]::NewLine + "ServiceRoot=$resolvedRoot" + [Environment]::NewLine
}

. (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'skin-settings.ps1')
if ($content -notmatch '(?m)^SkinScale=') {
  $widthMatch = [regex]::Match($content, '(?m)^SkinWidth=(\d+)')
  $scale = if ($widthMatch.Success) { [Math]::Max(0.75, [Math]::Min(1.8, [int]$widthMatch.Groups[1].Value / 208)) } else { 1 }
  $content = Set-SkinVariable $content 'SkinScale' $scale.ToString([Globalization.CultureInfo]::InvariantCulture)
}
if ($content -notmatch '(?m)^DashboardUrl=') {
  $uri = if ($statusMatch.Success) { [UriBuilder]$statusMatch.Groups[1].Value } else { [UriBuilder]'http://127.0.0.1:8767/' }
  $uri.Path = $uri.Path -replace '/rainmeter/?$', '/'
  $uri.Query = ''
  $uri.Fragment = ''
  $content = Set-SkinVariable $content 'DashboardUrl' $uri.Uri.AbsoluteUri
}
if ($content -notmatch '(?m)^HistoryUrl=') {
  $dashboardMatch = [regex]::Match($content, '(?m)^DashboardUrl=([^\r\n]+)')
  $history = [UriBuilder]$dashboardMatch.Groups[1].Value
  $history.Fragment = 'history'
  $content = Set-SkinVariable $content 'HistoryUrl' $history.Uri.AbsoluteUri
}
foreach ($entry in @{ OfflineAfterSeconds = '10'; RailLineColor = '52,196,218,92' }.GetEnumerator()) {
  if ($content -notmatch ('(?m)^' + $entry.Key + '=')) { $content = Set-SkinVariable $content $entry.Key $entry.Value }
}
[IO.File]::WriteAllText($resolvedVariables, $content, [Text.Encoding]::Unicode)
