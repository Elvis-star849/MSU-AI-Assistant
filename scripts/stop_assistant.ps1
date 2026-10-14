# Stop the MSU AI Assistant server started by start_assistant.ps1 (uses logs\assistant.pid).
$ErrorActionPreference = "Stop"
$pidFile = Join-Path (Split-Path -Parent $PSScriptRoot) "logs\assistant.pid"
if (-not (Test-Path $pidFile)) { Write-Output "No PID file: nothing to stop."; exit 0 }
$serverPid = [int](Get-Content $pidFile)
$proc = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
if ($proc) {
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$serverPid" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false }
    Stop-Process -Id $serverPid -Force -Confirm:$false
    Write-Output "Stopped PID $serverPid."
} else { Write-Output "PID $serverPid is not running." }
Remove-Item $pidFile -Confirm:$false
