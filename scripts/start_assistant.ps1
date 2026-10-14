# Start the MSU AI Assistant as a detached background server (Windows PowerShell).
#   .\scripts\start_assistant.ps1                      C3 profile (default), http://localhost:8502
#   .\scripts\start_assistant.ps1 -Profile baseline    rollback configuration
#   .\scripts\start_assistant.ps1 -Port 8510 -Address 127.0.0.1
# The Groq key is read from the environment or the Git-ignored .env file; it is never printed or logged.
param(
    [ValidateSet("c3_public_0005", "baseline")] [string]$Profile = "c3_public_0005",
    [int]$Port = 8502,
    [string]$Address = "127.0.0.1"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$logs = Join-Path $root "logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$env:MSU_ASSISTANT_PROFILE = $Profile
$env:HF_HUB_OFFLINE = "1"
$streamlitArgs = @("-m", "streamlit", "run", "app.py", "--server.port", "$Port", "--server.address", $Address,
          "--server.headless", "true", "--browser.gatherUsageStats", "false")
$proc = Start-Process -FilePath "python" -ArgumentList $streamlitArgs -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logs "assistant.out.log") -RedirectStandardError (Join-Path $logs "assistant.err.log")
Set-Content -Path (Join-Path $logs "assistant.pid") -Value $proc.Id
Write-Output "MSU AI Assistant starting (PID $($proc.Id), profile $Profile) at http://${Address}:$Port"
Write-Output "Health: python healthcheck.py --url http://${Address}:$Port"
