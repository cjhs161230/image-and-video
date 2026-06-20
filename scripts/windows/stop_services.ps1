$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))

foreach ($pidFile in @("data\pids\web.pid", "data\pids\worker.pid")) {
    if (Test-Path -LiteralPath $pidFile) {
        $pidValue = [int](Get-Content -LiteralPath $pidFile -Raw)
        $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($process) {
            Stop-Process -Id $pidValue
        }
        Remove-Item -LiteralPath $pidFile -Force
    }
}

Write-Host "已按 PID 文件停止本项目进程。"
