import { readFileSync } from "node:fs";
import assert from "node:assert/strict";

const html = readFileSync("frontend/index.html", "utf8");
const js = readFileSync("frontend/js/app.js", "utf8");
const source = `${html}\n${js}`;

for (const text of ["图片工作台", "历史", "设置"]) {
  assert.match(source, new RegExp(text));
}

for (const text of [
  "暂停",
  "继续",
  "取消",
  "生成图片",
  "刷新历史",
  "删除记录",
  "保存设置",
  "/api/v1/image-jobs",
  "/api/v1/jobs",
  "/api/v1/estimates/storage",
  "/api/v1/history",
  "confirm=true",
  "/api/v1/settings",
  "积分估算",
  "磁盘估算",
  "确认成本",
  "尺寸",
  "审核强度",
  "压缩质量",
  "输入保真度",
  "图生图输入",
  "image-input-files",
  "凭证配置状态",
  "createDebouncedDraftSaver",
  "800",
  "data-nav-link",
  "is-active",
  "界面背景",
  "清爽浅色",
  "data-theme",
  "theme-light",
  "getControlActionsForStatus",
  "视频功能已归档",
]) {
  assert.match(source, new RegExp(text));
}

assert.doesNotMatch(html, /option value="app"/);
assert.match(html, /<section id="image-workbench"[^>]*data-page/);
assert.match(html, /<section id="history"[^>]*data-page/);
assert.match(html, /<section id="settings"[^>]*data-page/);
assert.doesNotMatch(html, /data-nav-link="video-projects"/);
assert.doesNotMatch(html, /<section id="video-projects"[^>]*data-page/);
assert.doesNotMatch(html, />起始帧</);
assert.doesNotMatch(html, />总帧数</);
assert.doesNotMatch(html, />结束帧</);
