function Get-RainmeterSkinPath([string]$SkinPath = '', [string]$SettingsPath = '') {
  if (-not [string]::IsNullOrWhiteSpace($SkinPath)) {
    return [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($SkinPath))
  }
  $candidates = [System.Collections.Generic.List[string]]::new()
  if ($SettingsPath) {
    if (-not (Test-Path -LiteralPath $SettingsPath -PathType Leaf)) { throw "Rainmeter settings file does not exist: $SettingsPath" }
    $candidates.Add($SettingsPath)
  }
  if ($env:CODEX_RAINMETER_SETTINGS) { $candidates.Add($env:CODEX_RAINMETER_SETTINGS) }
  foreach ($process in @(Get-CimInstance Win32_Process -Filter "Name = 'Rainmeter.exe'" -ErrorAction SilentlyContinue)) {
    $match = [regex]::Match([string]$process.CommandLine, '(?i)(?:^|\s)-c\s+(?:"([^"]+)"|(\S+))')
    if ($match.Success) {
      $config = if ($match.Groups[1].Success) { $match.Groups[1].Value } else { $match.Groups[2].Value }
      if (-not [IO.Path]::IsPathRooted($config) -and $process.ExecutablePath) {
        $config = Join-Path (Split-Path -Parent $process.ExecutablePath) $config
      }
      $candidates.Add($config)
    }
    if ($process.ExecutablePath) { $candidates.Add((Join-Path (Split-Path -Parent $process.ExecutablePath) 'Rainmeter.ini')) }
  }
  if ($env:APPDATA) { $candidates.Add((Join-Path $env:APPDATA 'Rainmeter\Rainmeter.ini')) }
  foreach ($config in $candidates) {
    if (-not (Test-Path -LiteralPath $config -PathType Leaf)) { continue }
    $text = [IO.File]::ReadAllText($config)
    $section = [regex]::Match($text, '(?ims)^\[Rainmeter\]\s*\r?\n(.*?)(?=^\[|\z)')
    $match = [regex]::Match($section.Groups[1].Value, '(?im)^SkinPath\s*=\s*([^\r\n]+)')
    if ($match.Success) {
      $path = [Environment]::ExpandEnvironmentVariables($match.Groups[1].Value.Trim().Trim('"'))
      if (-not [IO.Path]::IsPathRooted($path)) { $path = Join-Path (Split-Path -Parent $config) $path }
      return [IO.Path]::GetFullPath($path)
    }
  }
  # The Windows known folder follows OneDrive and other Documents redirections.
  return Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Rainmeter\Skins'
}
