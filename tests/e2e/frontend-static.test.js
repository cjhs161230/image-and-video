import { readFileSync } from "node:fs";
import assert from "node:assert/strict";

const html = readFileSync("frontend/index.html", "utf8");
const js = readFileSync("frontend/js/app.js", "utf8");
const source = `${html}\n${js}`;

for (const text of ["图片工作台", "视频项目", "历史", "设置"]) {
  assert.match(source, new RegExp(text));
}

for (const text of [
  "暂停",
  "继续",
  "取消",
  "分镜确认",
  "关键帧确认",
  "积分估算",
  "磁盘估算",
  "凭证配置状态",
]) {
  assert.match(source, new RegExp(text));
}
