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

function Test-LocalPortAvailable {
    param(
        [string]$HostName,
        [int]$Port
    )

    $address = [System.Net.IPAddress]::Parse($HostName)
    $listener = [System.Net.Sockets.TcpListener]::new($address, $Port)
    try {
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        $listener.Stop()
    }
}

$hostSetting = if ($env:IMAGE_VIDEO_HOST) { $env:IMAGE_VIDEO_HOST } else { Get-DotEnvValue "IMAGE_VIDEO_HOST" }
if (-not $hostSetting) {
    $hostSetting = "127.0.0.1"
}
if ($hostSetting -ne "127.0.0.1") {
    Write-Error "IMAGE_VIDEO_HOST 只能是 127.0.0.1。"
}

$portSetting = if ($env:IMAGE_VIDEO_PORT) { $env:IMAGE_VIDEO_PORT } else { Get-DotEnvValue "IMAGE_VIDEO_PORT" }
if (-not $portSetting) {
    $portSetting = "17860"
}
$webPort = 0
if (-not [int]::TryParse($portSetting, [ref]$webPort) -or $webPort -lt 1 -or $webPort -gt 65535) {
    Write-Error "IMAGE_VIDEO_PORT 必须是 1 到 65535 的整数。"
}
if (-not (Test-LocalPortAvailable -HostName $hostSetting -Port $webPort)) {
    Write-Error "端口 $webPort 已被占用。请在 .env 中设置 IMAGE_VIDEO_PORT 为未占用端口。"
}

New-Item -ItemType Directory -Force -Path "data", "data\pids" | Out-Null
$uvCacheDir = if ($env:IMAGE_VIDEO_UV_CACHE_DIR) {
    $env:IMAGE_VIDEO_UV_CACHE_DIR
} else {
    "data\uv-cache"
}
New-Item -ItemType Directory -Force -Path $uvCacheDir | Out-Null

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv 未安装或不在 PATH 中。"
}

$database = "data\db\workbench.db"
if (Test-Path -LiteralPath $database) {
    uv --cache-dir $uvCacheDir run python scripts\windows\prepare_database.py
    $prepareExit = $LASTEXITCODE
    if ($prepareExit -eq 2) {
        uv --cache-dir $uvCacheDir run alembic stamp head
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    } elseif ($prepareExit -ne 0) {
        exit $prepareExit
    }
}

uv --cache-dir $uvCacheDir run alembic upgrade head
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$ffmpeg = "D:\ffmpeg\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe"
if (-not (Test-Path -LiteralPath $ffmpeg)) {
    Write-Error "ffmpeg 不存在：$ffmpeg"
}

$web = Start-Process -FilePath "uv" -ArgumentList @(
    "--cache-dir", $uvCacheDir, "run", "uvicorn", "image_video.main:app",
    "--host", $hostSetting, "--port", $webPort
) -PassThru -WindowStyle Hidden
Set-Content -Path "data\pids\web.pid" -Value $web.Id

$worker = Start-Process -FilePath "uv" -ArgumentList @(
    "--cache-dir", $uvCacheDir, "run", "python", "-m", "image_video.worker.main"
) -PassThru -WindowStyle Hidden
Set-Content -Path "data\pids\worker.pid" -Value $worker.Id

$url = "http://$($hostSetting):$webPort"
Start-Process $url
Write-Host "已启动 Web 和 Worker：$url"
