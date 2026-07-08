# 图片生成工作台

Windows 本机单用户 AI 图片生成工作台。Web 服务只监听 `127.0.0.1`，后端使用 FastAPI、独立 Worker、SQLite/Alembic，前端使用原生 HTML/CSS/JavaScript。

当前计划见 [PLAN.md](PLAN.md)，状态为 `Active`、版本为 2.0。项目当前默认聚焦图片生成、图生图、历史、设置和受控媒体访问。

## 当前定位

- 默认项目定位：图片生成工作台。
- 视频功能状态：已归档 / 默认停用 / 可恢复。
- 默认开关：`VIDEO_FEATURE_ENABLED=false`。
- 视频归档目录：`archive/video_feature_20260708/`。

看到 `video-projects`、`storyboard`、`keyframe`、`frame`、`video handler`、video migration 或 video model 时，应理解为归档兼容和未来恢复能力，不表示默认启用的视频功能。

## 默认可用功能

- `/api/v1` 基础接口、统一响应、配置状态、模型列表、公开设置和统一任务控制。
- 普通图片文生图 / 图生图任务，支持最多 8 张输入图、受控媒体保存、缩略图、历史摘要和任务控制。
- SQLite 持久化任务队列，支持 `image.generate` 的暂停、继续、取消、lease、heartbeat 和重启恢复。
- Matsca GPT-Image-2 `direct/native`、DashScope 图片模型和本地受控媒体访问。
- 历史页展示图片记录；遇到旧视频记录时只做归档兼容展示，不引导继续视频流程。
- 设置页保留旧公开设置兼容字段，密钥仍只从本地环境读取。

## 视频归档行为

默认 `VIDEO_FEATURE_ENABLED=false` 时：

- 不挂载完整视频 router，只挂载轻量归档 router。
- 不初始化 DeepSeek 视频规划器、Matsca 视频关键帧生成器、Matsca 连续帧生成器或 FFmpeg 视频合成链路。
- Worker 只注册 `image.generate`，不领取 `video.*` queued job。
- 前端不展示“视频项目”入口。
- `/api/v1/video-projects` 及旧子路径返回 `410 VIDEO_FEATURE_ARCHIVED`。
- 旧数据库、旧 video migration、video SQLAlchemy model 和旧设置字段保留，以支持历史兼容和未来恢复。

恢复说明见 [archive/video_feature_20260708/restore-notes.md](archive/video_feature_20260708/restore-notes.md)。真实 DeepSeek / Matsca / FFmpeg smoke 必须单独取得用户授权。

## 安全与配置

复制 `.env.example` 为 `.env`，只在 `.env` 中填写真实凭证。不要提交 `.env`、`data/`、日志、数据库、上传文件、生成媒体或迁移产物。

支持的环境变量：

- `IMAGE_VIDEO_HOST`，建议固定为 `127.0.0.1`
- `IMAGE_VIDEO_PORT`，默认 `17860`
- `VIDEO_FEATURE_ENABLED`，默认 `false`
- `DASHSCOPE_API_KEY`
- `MATSCA_DIRECT_BASE_URL`
- `MATSCA_DIRECT_API_KEY`
- `MATSCA_NATIVE_BASE_URL`
- `MATSCA_NATIVE_API_KEY`
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_API_KEY`
- `DEEPSEEK_MODEL`

公开运行设置写入 Git 忽略的 `data/settings.json`，包括 `ffmpeg_path`、`native_download_proxy`、`matsca_direct_concurrency`、`matsca_native_concurrency` 和 `cost_rates`。其中 `ffmpeg_path` 与 `cost_rates.video_per_frame` 属于归档视频兼容字段，本轮不删除。

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
uv --cache-dir .uv-cache run pytest -q
uv --cache-dir .uv-cache run ruff check .
uv --cache-dir .uv-cache run pyright
npm run lint
npm run format:check
npm run test:e2e
python scripts\security\scan_secrets.py .
```

`npm run test:e2e` 当前是 Node 侧静态页面/API 客户端测试，不是真实浏览器端到端验收。真实上游验收必须由用户明确授权。

## 文档

- [执行计划](PLAN.md)：唯一计划与进度来源。
- [开发指南](docs/guide.md)：架构、运行、配置、迁移、归档边界和恢复原则。
- [API 概览](docs/api.md)：当前 `/api/v1` 路由和归档视频接口说明。
- [视频归档目录](archive/video_feature_20260708/README.md)：旧视频功能归档与恢复参考。

## 固定边界

- 仅支持 Windows 本机单用户。
- Web 服务只监听 `127.0.0.1`。
- API 统一为 `/api/v1`，不保留旧 API。
- 不实现音频、真正视频模型、远程访问、多用户、Linux/macOS 支持、GitHub Actions 或 React/Vue。

GitHub 私有仓库：

```text
https://github.com/cjhs161230/image-and-video.git
```
