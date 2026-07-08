import { existsSync, readFileSync } from "node:fs";
import assert from "node:assert/strict";

assert.ok(existsSync("start.bat"));
assert.ok(existsSync("stop.bat"));

const start = readFileSync("start.bat", "utf8");
const stop = readFileSync("stop.bat", "utf8");
const startPs1 = readFileSync("scripts/windows/start_services.ps1", "utf8");
const stopPs1 = readFileSync("scripts/windows/stop_services.ps1", "utf8");
const startSource = `${start}\n${startPs1}`;
const stopSource = `${stop}\n${stopPs1}`;

for (const text of ["uv", "alembic upgrade head", "ffmpeg", "uvicorn", "worker.pid", "web.pid"]) {
  assert.match(startSource, new RegExp(text, "i"));
}

assert.match(startSource, /IMAGE_VIDEO_PORT/i);
assert.match(startSource, /IMAGE_VIDEO_UV_CACHE_DIR/i);
assert.match(startSource, /data\\uv-cache/i);
assert.match(startSource, /17860/i);
assert.match(startSource, /Start-Process\s+\$url/i);
assert.match(start, /--hidden/i);
assert.match(startPs1, /\$Hidden/i);
assert.match(startPs1, /-NoExit/i);
assert.match(startPs1, /Start-ServiceProcess/i);
assert.match(startPs1, /WindowStyle\s+Hidden/i);
assert.match(
  startPs1,
  /Start-ServiceProcess -Name "Web" -Arguments \$webArguments -PidPath "data\\pids\\web\.pid" -Hidden:\$Hidden/i,
);
assert.match(
  startPs1,
  /Start-ServiceProcess -Name "Worker" -Arguments \$workerArguments -PidPath "data\\pids\\worker\.pid" -Hidden:\$Hidden/i,
);
assert.doesNotMatch(startSource, /--port",\s*"8000/i);
assert.doesNotMatch(startSource, /http:\/\/127\.0\.0\.1:8000/i);
assert.match(stopSource, /web\.pid/i);
assert.match(stopSource, /worker\.pid/i);
assert.doesNotMatch(stopSource, /taskkill\s+\/im/i);
assert.match(stopPs1, /taskkill\.exe/i);
assert.match(stopPs1, /\/pid/i);
assert.match(stopPs1, /\/t/i);
assert.match(stop, /EnableDelayedExpansion/i);
assert.match(stop, /PS_ARGS/i);
assert.match(stop, /shift/i);
assert.match(stop, /--clean-cache/i);
assert.match(stop, /--clean-uv-cache/i);
assert.match(stop, /--force-port/i);
assert.match(stopPs1, /param\s*\(/i);
assert.match(stopPs1, /\$CleanCache/i);
assert.match(stopPs1, /\$CleanUvCache/i);
assert.match(stopPs1, /\$ForcePort/i);
assert.match(stopPs1, /IMAGE_VIDEO_PORT/i);
assert.match(stopPs1, /Get-NetTCPConnection/i);
assert.match(stopPs1, /netstat\s+-ano/i);
assert.match(stopPs1, /Stop-Process\s+-Id\s+\$pidValue\s+-Force/i);
assert.match(stopPs1, /catch/i);
assert.match(stopPs1, /无法清理/i);
assert.match(stopPs1, /data\\uv-cache/i);
assert.match(stopPs1, /__pycache__/i);
assert.match(stopPs1, /\.pytest_cache/i);
assert.match(stopPs1, /\.ruff_cache/i);
assert.doesNotMatch(stopPs1, /Remove-Item\s+-LiteralPath\s+["']?data["']?/i);
assert.doesNotMatch(stopPs1, /Remove-Item\s+-LiteralPath\s+["']?\.env["']?/i);
