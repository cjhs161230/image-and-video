# 图像与视频工作台

面向 Windows 本机单用户的 AI 图像生成与逐帧视频工作台。

项目正在按照 [`PLAN.md`](PLAN.md) 重建。当前计划状态为 `Active`，阶段 0–12 已完成验证；阶段 13“验证、GitHub 私有仓库和旧项目归档”尚未完成。当前已具备基础 API、持久化队列、供应商适配、普通图片任务、视频分镜门禁、关键帧门禁、连续帧生成、补帧、MP4 合成、统一历史、受控媒体访问、中文前端骨架、旧数据迁移、启动/停止脚本和文档。

## 当前进度

已完成：

- 安全基线、项目骨架、`.gitignore`、`.env.example` 和 agent 规则。
- FastAPI `/api/v1` 基础接口、统一响应、配置状态、模型列表和普通设置 API。
- SQLite、SQLAlchemy、Alembic 和持久化任务队列。
- 任务暂停、继续、取消、lease、heartbeat 和重启恢复。
- DashScope 四个图片模型适配。
- Matsca GPT-Image-2 `app`、`direct`、`native` 三种调用模式适配。
- DeepSeek 分镜规划、复审和有限重试。
- 普通图片任务提交、状态查询、媒体保存、缩略图和元数据记录。
- 视频项目草稿、最多 8 张带文字标注参考图、分镜生成、分镜版本和用户确认。
- 视频关键帧生成、预览列表、指定重生成、相邻片段失效标记和关键帧确认前暂停。
- 视频连续帧生成、参考图限制、缺失/失效帧补生成、超时人工处理和 FFmpeg 静音 H.264/yuv420p MP4 合成。
- 图片/视频统一历史、视频封面、日志摘要、受控媒体访问和二次确认删除。
- 图片工作台、视频项目、历史和设置四个中文前端页面骨架。
- 旧 SQLite 数据库只读快照、媒体复制、SHA-256 校验、缺失标记、日志归档和迁移报告。
- `start.bat` / `stop.bat` 和中文需求、架构、开发、API、迁移文档。

未完成：

- Matsca 图片真实 smoke test 尚未形成完整通过结论：DeepSeek 与 FFmpeg smoke 已通过；Matsca direct 曾返回 502；Matsca native 能返回图片 URL，但结果图下载阶段可能需要代理。
- 阶段 13 最终完成标记仍未完成。

## 安全说明

- API 密钥只允许写入本地 `.env`，不要提交 `.env`。
- 不要复制旧项目的 `.env` 或 `config.json`。
- 旧项目中曾明文保存过的 DashScope、Matsca、DeepSeek 凭证已由用户确认完成轮换。
- `data/`、日志、数据库、上传文件和生成媒体均不会进入 Git。
- 普通设置写入 `data/settings.json`；设置 API 不接收密钥字段。
- 提交或推送前必须运行秘密扫描：`python scripts/security/scan_secrets.py .`

## 本地开发

后端使用 Python 3.11、uv、FastAPI、SQLAlchemy 2 和 Alembic。

常用验证命令：

```powershell
uv --cache-dir .uv-cache run pytest -q --basetemp=data\test-tmp
uv --cache-dir .uv-cache run ruff check .
uv --cache-dir .uv-cache run pyright
npm run lint
npm run format:check
python scripts/security/scan_secrets.py .
```

如果本机 uv 默认缓存目录权限异常，可使用项目内 `.uv-cache`，如上面的命令所示。

## 文档

- [需求说明](docs/requirements.md)
- [架构说明](docs/architecture.md)
- [开发说明](docs/development.md)
- [API 概览](docs/api.md)
- [旧数据迁移](docs/migration.md)

## 配置

复制 `.env.example` 为 `.env`，只在 `.env` 中填写真实凭证。

支持的密钥和配置项包括：

- `IMAGE_VIDEO_HOST`，固定建议 `127.0.0.1`
- `IMAGE_VIDEO_PORT`，默认 `17860`，如端口被占用可在 `.env` 中改为其他未占用端口
- `DASHSCOPE_API_KEY`
- `MATSCA_APP_BASE_URL`
- `MATSCA_APP_API_KEY`
- `MATSCA_APP_ID`
- `MATSCA_APP_SECRET`
- `MATSCA_DIRECT_BASE_URL`
- `MATSCA_DIRECT_API_KEY`
- `MATSCA_NATIVE_BASE_URL`
- `MATSCA_NATIVE_API_KEY`
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_API_KEY`
- `DEEPSEEK_MODEL`，默认建议 `deepseek-v4-flash`

FFmpeg 默认路径：

```text
D:\ffmpeg\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe
```

`start.bat` 会读取 `.env` 中的 `IMAGE_VIDEO_HOST` / `IMAGE_VIDEO_PORT`，启动前检查端口是否可用，并只允许 Web 服务绑定到 `127.0.0.1`。默认端口为 `17860`，用于避开常见的 `8000` 及附近端口冲突。

### Matsca 模式说明

Matsca 接入文档确认支持 `app`、`direct`、`native` 三种 Key 级调用模式，本项目第一版不支持商用模式。

- `app`：需要 `Authorization`、`X-App-ID`、`X-App-Secret`，官方并发上限 2，本项目保守并发为 1。
- `direct`：只需要 `Authorization`，官方并发上限 10，本项目保守并发为 5。
- `native`：同步图片接口走官方 API 直连，官方并发上限 100，本项目保守并发为 50。该模式通常返回图片 URL；如果本机无法直接访问官方图片资源，下载结果图时需要配置 HTTP/SOCKS 代理。

普通设置中的 `native_download_proxy` 用于 native 图片 URL 下载阶段，例如 `http://127.0.0.1:7890`。没有代理或可直连官方图片资源时可留空。若 native 模式已返回图片 URL，但下载时报 `403 Forbidden`、连接超时或无法访问官方资源，优先在设置中配置该代理后重试下载/生成。

图片接口按 Matsca 文档使用：

- `POST /v1/images/generations`
- `POST /v1/images/edits`
- `response_format=b64_json` 或 `response_format=url`
- `n=1~4`
- 图生图最多 8 张输入图

当前后台 Worker 入口仍处于最小启动占位状态；图片任务处理器已支持 native URL 下载代理，但完整 Worker 消费循环仍需在后续实现或验收中闭合。

## 当前 API 概览

基础接口：

- `GET /api/v1/health`
- `GET /api/v1/models`
- `GET /api/v1/config/status`
- `GET /api/v1/settings`
- `PATCH /api/v1/settings`

图片任务：

- `POST /api/v1/image-jobs`
- `GET /api/v1/image-jobs/{job_id}`
- `POST /api/v1/image-jobs/{job_id}/pause`
- `POST /api/v1/image-jobs/{job_id}/resume`
- `POST /api/v1/image-jobs/{job_id}/cancel`

视频分镜：

- `POST /api/v1/video-projects`
- `PATCH /api/v1/video-projects/{project_id}/draft`
- `POST /api/v1/video-projects/{project_id}/storyboard/generate`
- `POST /api/v1/video-projects/{project_id}/storyboard/versions`
- `GET /api/v1/video-projects/{project_id}/storyboard/versions`
- `POST /api/v1/video-projects/{project_id}/storyboard/versions/{version_id}/confirm`

视频关键帧：

- `POST /api/v1/video-projects/{project_id}/keyframes/generate`
- `GET /api/v1/video-projects/{project_id}/keyframes`
- `POST /api/v1/video-projects/{project_id}/keyframes/{frame}/regenerate`
- `POST /api/v1/video-projects/{project_id}/keyframes/confirm`

视频连续帧与合成：

- `POST /api/v1/video-projects/{project_id}/frames/generate`
- `POST /api/v1/video-projects/{project_id}/frames/{frame}/repair`
- `POST /api/v1/video-projects/{project_id}/stitch`

历史与媒体：

- `GET /api/v1/history`
- `GET /api/v1/history?kind=image`
- `GET /api/v1/history?kind=video`
- `GET /api/v1/media/{media_id}`
- `DELETE /api/v1/media/{media_id}?confirm=true`

旧数据迁移：

```powershell
python scripts\migration\migrate_legacy.py <legacy_root> <legacy_database>
```

迁移会写入 `data/migration`，使用 SQLite backup API 创建只读快照，复制可定位媒体并生成 `migration_report.json`；旧密钥配置不会导入。

## 固定产品约束

- 仅支持 Windows 本机单用户。
- Web 服务只监听 `127.0.0.1`。
- API 统一为 `/api/v1`，不保留旧 API。
- 不实现 Matsca 商用模式、音频、真正视频模型、远程访问、多用户、Linux/macOS 支持或 React/Vue 前端。

## GitHub 发布状态

本地 `main` 当前跟踪 `origin/main`，远程仓库为：

```text
https://github.com/cjhs161230/image-and-video.git
```

仓库已完成首次推送；旧项目已归档到 `E:\auxiliary tool\archives\wan-image-viewer`。计划完成标记仍按 [`PLAN.md`](PLAN.md) 阶段 13 执行。
