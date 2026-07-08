# 开发指南

当前进度以根目录 `PLAN.md` 为准，用户入口以 `README.md` 为准，API 细节见 `docs/api.md`。

## 产品边界

- Windows 本机单用户，Web 服务只监听 `127.0.0.1`。
- 后端使用 FastAPI、独立 Worker、SQLite、SQLAlchemy 2、Alembic。
- 前端使用原生 HTML/CSS/JavaScript，不引入 React/Vue。
- 当前默认主线为图片生成、图生图、历史、设置和受控媒体。
- 视频功能已归档 / 默认停用 / 可恢复，默认 `VIDEO_FEATURE_ENABLED=false`。
- 不实现远程访问、多用户、Linux/macOS、音频、真正视频模型、旧 API 兼容或 GitHub Actions。

## 架构

- `src/image_video/api/`：HTTP API。默认视频路径由 `video_projects_archived.py` 返回归档错误。
- `src/image_video/application/`：应用服务和流程编排。视频服务代码保留作恢复能力。
- `src/image_video/infrastructure/`：配置、数据库、供应商适配、日志。
- `src/image_video/worker/`：Worker Runner、图片任务处理和归档视频 handler 参考。
- `frontend/`：中文本地前端，默认不展示视频项目入口。
- `archive/video_feature_20260708/`：视频功能归档和恢复参考。
- `data/`：数据库、日志、上传、生成媒体、迁移报告和 PID 文件，不进入 Git。

数据库启用 WAL、foreign keys 和 busy timeout。video SQLAlchemy model 和 video migration 保留，因为旧数据库可能已有 video 表和记录，Alembic 全链路也需要历史结构。

## Worker

默认 Worker handlers 只包含：

- `image.generate`

`JobQueue.claim_next(..., allowed_kinds=set(self.handlers))` 会限制领取任务类型。默认关闭视频功能时，`video.*` queued job 留在队列中，不领取、不失败、不取消。

只有 `VIDEO_FEATURE_ENABLED=true` 时，Worker 才局部导入并注册：

- `video.storyboard.generate`
- `video.storyboard.review`
- `video.keyframes.generate`
- `video.keyframe.regenerate`
- `video.frames.generate`
- `video.frame.repair`
- `video.stitch`

## 配置

密钥只从本地环境读取；公开运行设置写入 `data/settings.json`。`.env.example` 包含 `VIDEO_FEATURE_ENABLED=false`。

公开设置包括 `ffmpeg_path`、`native_download_proxy`、`matsca_direct_concurrency`、`matsca_native_concurrency` 和 `cost_rates`。其中 `ffmpeg_path`、`cost_rates.video_per_frame` 属于归档视频兼容字段，本轮不删除，也不设计 settings migration。

默认关闭视频功能时，启动项目不依赖 DeepSeek、Matsca 视频生成或 FFmpeg 配置完整存在。

## 视频归档与恢复原则

默认关闭时：

- 不挂载完整视频 router。
- 不初始化 DeepSeek 视频规划器。
- 不初始化 Matsca 视频关键帧生成器。
- 不初始化 Matsca 连续帧生成器。
- 不初始化 FFmpeg 视频合成链路。
- 前端不展示“视频项目”入口。

禁止删除旧数据库、清空 `data/`、新增 drop-table migration、移动/删除/重写 video migration，或把视频功能描述为“已删除”。

恢复时参考 `archive/video_feature_20260708/restore-notes.md`。真实付费 smoke 必须单独取得用户授权。

## 启动、迁移与验证

启动：

```powershell
start.bat
```

停止：

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

`npm run test:e2e` 当前是 Node 侧静态页面/API 客户端测试，不是真实浏览器端到端验收。
