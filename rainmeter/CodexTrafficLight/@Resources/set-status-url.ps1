param(
  [string]$Url = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VariablesFile = Join-Path $ScriptDir "variables.inc"
. (Join-Path $ScriptDir "skin-settings.ps1")

if ([string]::IsNullOrWhiteSpace($Url)) {
  Add-Type -AssemblyName Microsoft.VisualBasic
  $Url = [Microsoft.VisualBasic.Interaction]::InputBox(
    "请输入完整状态接口地址。本机用 http://127.0.0.1:8767/rainmeter；跨电脑用 http://对方IP:8767/rainmeter?token=你的令牌。",
    "Codex 交通灯状态接口",
    "http://127.0.0.1:8767/rainmeter"
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
$tasksBuilder = [UriBuilder]$uri
$normalizedPath = $builder.Path.TrimEnd("/")
if ($normalizedPath.EndsWith("/rainmeter", [StringComparison]::OrdinalIgnoreCase)) {
  $builder.Path = $normalizedPath.Substring(0, $normalizedPath.Length - "/rainmeter".Length) + "/status"
}
$JsonUrl = $builder.Uri.AbsoluteUri
$tasksPath = $tasksBuilder.Path.TrimEnd("/")
if ($tasksPath.EndsWith("/rainmeter", [StringComparison]::OrdinalIgnoreCase)) {
  $tasksBuilder.Path = $tasksPath.Substring(0, $tasksPath.Length - "/rainmeter".Length) + "/tasks"
}
$TasksUrl = $tasksBuilder.Uri.AbsoluteUri

$content = Get-Content -LiteralPath $VariablesFile -Raw -Encoding Unicode
$content = Set-SkinVariable $content 'StatusUrl' $Url
$content = Set-SkinVariable $content 'JsonStatusUrl' $JsonUrl
$content = Set-SkinVariable $content 'TasksUrl' $TasksUrl

$dashboardBuilder = [UriBuilder]$uri
$dashboardBuilder.Path = $normalizedPath -replace '/rainmeter$', '/'
$dashboardBuilder.Query = ''
$dashboardBuilder.Fragment = ''
$content = Set-SkinVariable $content 'DashboardUrl' $dashboardBuilder.Uri.AbsoluteUri
$dashboardBuilder.Fragment = 'history'
$content = Set-SkinVariable $content 'HistoryUrl' $dashboardBuilder.Uri.AbsoluteUri
Set-Content -LiteralPath $VariablesFile -Value $content -Encoding Unicode
Refresh-CodexSkins
