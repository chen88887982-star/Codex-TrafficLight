param([string]$ServiceRoot, [switch]$Repair, [string]$StatusUrl = '', [string]$VariablesPath = '')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
try {
  if ($StatusUrl) {
    $uri = [Uri]$StatusUrl
    if (-not $uri.IsLoopback) { throw '当前显示远程电脑。此按钮只维护本机服务；请到服务所在电脑执行体检/修复，或打开状态看板查看远程健康。' }
  }
  if ([string]::IsNullOrWhiteSpace($ServiceRoot) -or -not (Test-Path -LiteralPath $ServiceRoot -PathType Container)) {
    throw '未找到本机项目目录。请重新安装皮肤，或在服务所在电脑运行维护脚本。'
  }
  $doctor = Join-Path ([IO.Path]::GetFullPath($ServiceRoot)) 'win\codex_status_server\.internal\service-doctor.ps1'
  $port = if ($StatusUrl) { ([Uri]$StatusUrl).Port } else { 0 }
  & $doctor -Repair:$Repair -Port $port -VariablesPath $VariablesPath
  exit $LASTEXITCODE
} catch {
  [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'CodexTrafficLight 服务维护', 'OK', 'Warning') | Out-Null
  exit 1
}
