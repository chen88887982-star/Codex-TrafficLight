param([string]$ServiceRoot)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms

if ([string]::IsNullOrWhiteSpace($ServiceRoot) -or -not (Test-Path -LiteralPath $ServiceRoot -PathType Container)) {
  [System.Windows.Forms.MessageBox]::Show(
    "未找到状态服务项目目录。请重新运行 install-rainmeter-skin.cmd 后再试。",
    "CodexTrafficLight 服务体检",
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Warning
  ) | Out-Null
  exit 1
}

$doctor = Join-Path ([IO.Path]::GetFullPath($ServiceRoot)) "win\codex_status_server\.internal\service-doctor.ps1"
if (-not (Test-Path -LiteralPath $doctor -PathType Leaf)) {
  throw "未找到服务体检脚本：$doctor"
}
& $doctor -Repair
exit $LASTEXITCODE
