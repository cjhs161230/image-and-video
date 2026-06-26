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
  "生成图片",
  "保存草稿",
  "生成分镜",
  "确认分镜",
  "应用分镜编辑",
  "AI 复审分镜",
  "生成关键帧",
  "确认关键帧",
  "生成连续帧",
  "检查帧问题",
  "合成视频",
  "刷新历史",
  "进入项目",
  "删除记录",
  "保存设置",
  "/api/v1/image-jobs",
  "/api/v1/jobs",
  "/api/v1/video-projects",
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
  "参考图上传",
  "视频时长",
  "每秒帧数",
  "预计生成帧数",
  "图生图输入",
  "image-input-files",
  "video-reference-inputs",
  "toggle-video-references",
  "video-reference-summary",
  "reference-panel",
  "凭证配置状态",
  "storyboard-plan-editor",
  "storyboard-suggestion",
  "分镜结果",
  "分镜看板",
  "关键帧结果",
  "连续帧检查",
  "任务失败原因",
  "生成成功后会自动显示最新分镜",
  "选择分镜版本",
  "/storyboard/versions",
  "/storyboard/review",
  "createDebouncedDraftSaver",
  "800",
  "data-nav-link",
  "is-active",
  "界面背景",
  "清爽浅色",
  "data-theme",
  "theme-light",
  "getControlActionsForStatus",
  "deleteVideoProject",
  "播放视频",
  "删除项目",
  "openVideoProjectId",
  "restoreVideoProjectWorkspace",
]) {
  assert.match(source, new RegExp(text));
}

assert.doesNotMatch(html, /option value="app"/);
assert.match(html, /<section id="image-workbench"[^>]*data-page/);
assert.match(html, /<section id="video-projects"[^>]*data-page/);
assert.match(html, /<section id="history"[^>]*data-page/);
assert.match(html, /<section id="settings"[^>]*data-page/);
assert.doesNotMatch(html, />起始帧</);
assert.doesNotMatch(html, />总帧数</);
assert.doesNotMatch(html, />结束帧</);
