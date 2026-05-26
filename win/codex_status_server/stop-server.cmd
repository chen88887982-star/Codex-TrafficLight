@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -Command "$c=Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue; if($c){$c | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force; Write-Host ('Stopped process ' + $_) }} else { Write-Host 'No Codex status server found on port 8765.' }"

pause
