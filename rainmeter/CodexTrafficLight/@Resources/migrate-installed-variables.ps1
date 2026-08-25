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
  $content = [regex]::Replace($content, "(?m)^TasksUrl=.*$", "TasksUrl=$tasksUrl")
} else {
  $content = $content.TrimEnd() + [Environment]::NewLine + "TasksUrl=$tasksUrl" + [Environment]::NewLine
}
if ($content -match "(?m)^ServiceRoot=") {
  $content = [regex]::Replace($content, "(?m)^ServiceRoot=.*$", "ServiceRoot=$resolvedRoot")
} else {
  $content = $content.TrimEnd() + [Environment]::NewLine + "ServiceRoot=$resolvedRoot" + [Environment]::NewLine
}

[IO.File]::WriteAllText($resolvedVariables, $content, [Text.Encoding]::Unicode)
