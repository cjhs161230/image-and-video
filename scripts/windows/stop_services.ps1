param(
    [switch]$CleanCache,
    [switch]$CleanUvCache,
    [switch]$ForcePort
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))

function Get-DotEnvValue {
    param(
        [string]$Name
    )

    if (-not (Test-Path -LiteralPath ".env")) {
        return ""
    }

    foreach ($line in Get-Content -LiteralPath ".env") {
        $trimmed = $line.Trim()
        if ($trimmed -eq "" -or $trimmed.StartsWith("#")) {
            continue
        }
        if ($trimmed -match "^\s*$([regex]::Escape($Name))\s*=\s*(.*)\s*$") {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return ""
}

function Get-ConfiguredPort {
    $portSetting = if ($env:IMAGE_VIDEO_PORT) { $env:IMAGE_VIDEO_PORT } else { Get-DotEnvValue "IMAGE_VIDEO_PORT" }
    if (-not $portSetting) {
        $portSetting = "17860"
    }
    $port = 0
    if (-not [int]::TryParse($portSetting, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
        Write-Error "IMAGE_VIDEO_PORT 必须是 1 到 65535 的整数。"
    }
    return $port
}

function Stop-ConfiguredPortProcess {
    $port = Get-ConfiguredPort
    $processIds = @()
    $connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($connection in $connections) {
        $processIds += $connection.OwningProcess
    }

    $netstatLines = netstat -ano
    foreach ($line in $netstatLines) {
        if ($line -match "^\s*TCP\s+\S+:$port\s+\S+\s+LISTENING\s+(\d+)\s*$") {
            $processIds += [int]$Matches[1]
        }
    }

    foreach ($processId in $processIds | Sort-Object -Unique) {
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($process) {
            try {
                Stop-Process -Id $processId -Force
                Write-Host "已释放端口 $port：PID $processId ($($process.ProcessName))"
            } catch {
                Write-Warning "无法释放端口 $port 的 PID $processId ($($process.ProcessName))：$($_.Exception.Message)"
            }
        }
    }
}

function Remove-ProjectCachePath {
    param(
        [string]$Path,
        [string]$Label
    )

    $root = (Resolve-Path -LiteralPath ".").Path
    $parent = Split-Path -Parent $Path
    if (-not $parent) {
        $parent = "."
    }
    if (-not (Test-Path -LiteralPath $parent)) {
        return
    }

    $resolvedParent = (Resolve-Path -LiteralPath $parent).Path
    if (-not $resolvedParent.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        Write-Error "拒绝清理项目目录外的缓存：$Path"
    }

    if (Test-Path -LiteralPath $Path) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force
            Write-Host "已清理 $Label：$Path"
        } catch {
            Write-Warning "无法清理 $Label：$Path。$($_.Exception.Message)"
        }
    }
}

function Remove-PythonCacheDirectories {
    $excludedRoots = @(".git", ".venv", ".uv-cache", ".uv-python", "node_modules", "data")
    $queue = [System.Collections.Queue]::new()
    Get-ChildItem -LiteralPath "." -Directory -Force |
        Where-Object { $excludedRoots -notcontains $_.Name } |
        ForEach-Object { $queue.Enqueue($_) }

    while ($queue.Count -gt 0) {
        $directory = $queue.Dequeue()
        if ($directory.Name -eq "__pycache__") {
            try {
                Remove-Item -LiteralPath $directory.FullName -Recurse -Force
                Write-Host "已清理 Python 字节码缓存：$($directory.FullName)"
            } catch {
                Write-Warning "无法清理 Python 字节码缓存：$($directory.FullName)。$($_.Exception.Message)"
            }
            continue
        }

        try {
            Get-ChildItem -LiteralPath $directory.FullName -Directory -Force |
                Where-Object { $excludedRoots -notcontains $_.Name } |
                ForEach-Object { $queue.Enqueue($_) }
        } catch {
            Write-Warning "无法扫描缓存目录：$($directory.FullName)。$($_.Exception.Message)"
        }
    }
}

foreach ($pidFile in @("data\pids\web.pid", "data\pids\worker.pid")) {
    if (Test-Path -LiteralPath $pidFile) {
        $pidValue = [int](Get-Content -LiteralPath $pidFile -Raw)
        $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($process) {
            try {
                Stop-Process -Id $pidValue -Force
                & taskkill.exe /pid $pidValue /t /f 2>$null | Out-Null
            } catch {
                Write-Warning "无法停止 PID $pidValue ($($process.ProcessName))：$($_.Exception.Message)"
            }
        }
        Remove-Item -LiteralPath $pidFile -Force
    }
}

Write-Host "已按 PID 文件停止本项目进程。"

Stop-ConfiguredPortProcess
if ($ForcePort) {
    Write-Host "已执行显式端口释放检查。"
}

if ($CleanCache) {
    Remove-ProjectCachePath -Path ".pytest_cache" -Label "pytest 缓存"
    Remove-ProjectCachePath -Path ".ruff_cache" -Label "Ruff 缓存"
    Remove-ProjectCachePath -Path ".mypy_cache" -Label "mypy 缓存"
    Remove-ProjectCachePath -Path ".pyright" -Label "Pyright 缓存"
    Remove-ProjectCachePath -Path ".npm-cache" -Label "npm 缓存"
    Remove-PythonCacheDirectories
}

if ($CleanUvCache) {
    $uvCacheDir = if ($env:IMAGE_VIDEO_UV_CACHE_DIR) {
        $env:IMAGE_VIDEO_UV_CACHE_DIR
    } else {
        "data\uv-cache"
    }
    Remove-ProjectCachePath -Path $uvCacheDir -Label "uv 缓存"
}
