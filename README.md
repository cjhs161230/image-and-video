# 图像与视频工作台

Windows 本机单用户 AI 图像生成与逐帧视频工作台。Web 服务只监听 `127.0.0.1`，后端使用 FastAPI、独立 Worker、SQLite/Alembic，前端使用原生 HTML/CSS/JavaScript。

当前计划见 [PLAN.md](PLAN.md)，状态为 `Active`、版本为 1.5。项目已完成普通图片任务闭环，以及视频分镜、关键帧、连续帧、补帧、合成、成品受控访问、视频项目删除、真实产物估算和任务终态刷新等基础链路；真实浏览器端到端验收尚未执行。2026-06-24 已执行一次小样本真实付费视频 smoke：DeepSeek 分镜和 Matsca direct 关键帧通过，但连续帧失败，未生成 MP4，不能视为完整生产验收完成。

## 当前状态

已实现：

- `/api/v1` 基础接口、统一响应、配置状态、模型列表、公开设置和统一任务控制。
- SQLite 持久化任务队列，支持暂停、继续、取消、lease、heartbeat 和重启恢复；暂停/继续/取消只对可变状态生效，`completed` 等终态不会被改写。
- DashScope 图片模型、Matsca GPT-Image-2 `direct/native`、DeepSeek 分镜规划与独立复审。
- 普通图片文生图/图生图、最多 8 张输入图、受控媒体安全保存、缩略图和历史摘要；Matsca 返回 URL 时会先持久化恢复信息，下载失败后可只重新下载。
- 视频草稿、最多 8 张带文字标注参考图、分镜版本、AI 复审、两次人工门禁、关键帧重生成、相邻片段帧失效、连续帧、单帧修复和 FFmpeg 静音 MP4 合成。
- 视频成品通过受控 URL 访问；历史页支持所有视频项目记录，未完成/失败项目可进入视频工作台继续开发，完成项目可播放视频，图片媒体和视频项目支持二次确认删除。
- 基于已登记真实图片、视频帧和视频输出统计磁盘估算；无样本时回退到经验值。
- 中文前端的图片、视频项目、历史和设置工作区；视频项目按“视频时长（秒）+ 每秒帧数（FPS）”填写并自动换算帧范围；参考图区域默认收起，可按需展开；分镜生成/复审后会以可读看板展示关键帧和片段，关键帧结果会直接显示图片卡片，连续帧问题会显示时间点、原因和修复入口；任务失败会显示具体失败原因；支持右上角专属页面切换、设置页界面背景选择、终态任务控制按钮隐藏和视频任务终态后刷新相关视图；FastAPI 根路径提供本地前端。
- 旧 SQLite 数据只读迁移、媒体复制、SHA-256 校验和迁移报告。
- Web、Worker、供应商执行器结构化脱敏日志；Worker 会把本地解析和校验失败的安全摘要写入任务错误，便于前端和后续排查查看失败原因。
- 关键帧、连续帧和补帧会持久化稳定 `client_task_id`、上游任务 ID 和 URL 结果；已有 URL 时恢复只重新下载，不默认重新生成。

仍未完成或未通过：

- 真实浏览器端到端验收；当前 `npm run test:e2e` 是 Node 静态/API 客户端测试。
- 完整 DeepSeek/Matsca/FFmpeg 真实付费 smoke 尚未通过；最近一次 1 秒 / 10 FPS / 10 帧直连测试中，分镜和关键帧成功，连续帧任务以 `HTTPSTATUSERROR` 失败，视频输出不存在。本地已修复连续帧生产 Worker 接线，重启程序后需要重新验收。

## 安全与配置

复制 `.env.example` 为 `.env`，只在 `.env` 中填写真实凭证。不要提交 `.env`、`data/`、日志、数据库、上传文件、生成媒体或迁移产物。

支持的环境变量：

- `IMAGE_VIDEO_HOST`，建议固定为 `127.0.0.1`
- `IMAGE_VIDEO_PORT`，默认 `17860`
- `DASHSCOPE_API_KEY`
- `MATSCA_DIRECT_BASE_URL`
- `MATSCA_DIRECT_API_KEY`
- `MATSCA_NATIVE_BASE_URL`
- `MATSCA_NATIVE_API_KEY`
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_API_KEY`
- `DEEPSEEK_MODEL`

公开运行设置写入 Git 忽略的 `data/settings.json`，包括 `ffmpeg_path`、`native_download_proxy`、`matsca_direct_concurrency`、`matsca_native_concurrency` 和 `cost_rates`。设置 API 不接收密钥字段。

Matsca 当前只支持：

- `direct`：异步 `/api/image-tasks/generations|edits`，默认请求 `b64_json`，但结果同时兼容 `b64_json` 和 `url`；上游 task id 会持久化并在 Worker 重启后继续轮询。
- `native`：同步 `/v1/images/generations|edits`，默认请求 URL 结果；`native_download_proxy` 只用于下载返回的官方图片 URL。

`app`、商用模式、stream、variations、文本接口和 Responses API 当前不支持。

## 启动与验证

启动：

```powershell
start.bat
```

默认访问地址：`http://127.0.0.1:17860`。停止：

```powershell
stop.bat
```

常用验证：

```powershell
uv --cache-dir .uv-cache run pytest -q --basetemp=data\test-tmp
uv --cache-dir .uv-cache run ruff check .
uv --cache-dir .uv-cache run pyright
npm run lint
npm run format:check
npm run test:e2e
python scripts\security\scan_secrets.py .
```

`start.bat` 默认使用 `data\uv-cache` 作为 uv 缓存目录；如需临时覆盖可设置 `IMAGE_VIDEO_UV_CACHE_DIR`。

前端静态资源带版本查询参数；如果浏览器仍显示旧界面，优先使用 `Ctrl+F5` 强制刷新或打开无痕窗口。

## 文档

- [执行计划](PLAN.md)：唯一计划与进度来源。
- [开发指南](docs/guide.md)：架构、运行、配置、迁移、实现边界和已知缺口。
- [API 概览](docs/api.md)：当前 `/api/v1` 路由和关键请求说明。

## 固定边界

- 仅支持 Windows 本机单用户。
- Web 服务只监听 `127.0.0.1`。
- API 统一为 `/api/v1`，不保留旧 API。
- 不实现音频、真正视频模型、远程访问、多用户、Linux/macOS 支持、GitHub Actions 或 React/Vue。

GitHub 私有仓库：

```text
https://github.com/cjhs161230/image-and-video.git
```
