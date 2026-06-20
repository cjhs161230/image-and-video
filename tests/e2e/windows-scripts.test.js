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
assert.match(startSource, /17860/i);
assert.match(startSource, /Start-Process\s+\$url/i);
assert.doesNotMatch(startSource, /--port",\s*"8000/i);
assert.doesNotMatch(startSource, /http:\/\/127\.0\.0\.1:8000/i);
assert.match(stopSource, /web\.pid/i);
assert.match(stopSource, /worker\.pid/i);
assert.doesNotMatch(stopSource, /taskkill\s+\/im/i);
