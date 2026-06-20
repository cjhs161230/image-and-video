# 图像与视频工作台

面向 Windows 本机单用户的 AI 图像生成与逐帧视频工作台。

项目正在按照 [`PLAN.md`](PLAN.md) 重建。当前计划状态为 `Active`。审计后已闭合普通图片任务的基础链路：FastAPI 提交任务、独立 Worker 消费、SQLite 状态持久化、受控媒体结果和中文图片前端。视频分镜、关键帧、连续帧、合成与统一历史仍在重新验收，不能视为完整可用。

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
- 可操作的中文图片工作台：提交、状态轮询、暂停、继续、取消和结果展示。
- FastAPI 根路径提供本地前端和静态资源。
- Worker 启动时恢复过期 lease，领取图片任务并处理成功、失败和不确定超时。
- 旧 SQLite 数据库只读快照、媒体复制、SHA-256 校验、缺失标记、日志归档和迁移报告。
- `start.bat` / `stop.bat` 和中文需求、架构、开发、API、迁移文档。

未完成：

- 视频生成尚未统一进入持久化 Worker；当前视频接口仍包含同步执行路径。
- 片段间并行仍需实现；视频流程仍需完整启动与恢复验收。
- 视频项目、统一历史和完整设置前端仍未闭合。
- 历史 API 不返回本地绝对路径；图片历史使用受控媒体 URL，视频封面仍待闭合。
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

后台 Worker 已闭合普通图片任务消费，包括过期 lease 恢复、领取、心跳、成功/失败状态和超时 `needs_attention`。当前 Worker 尚未消费视频任务。

视频服务已补强以下正确性约束：

- 视频文件统一写入配置的 `data_root`，测试或自定义数据目录不再污染项目默认 `data/`。
- 分镜上游失败进入 `failed`，结果不确定的超时进入 `needs_attention`。
- 连续帧重复执行会跳过已完成文件，不再触发数据库唯一约束错误。
- 连续帧真实使用锚点、上一帧和用户参考图，单次输入不超过 8 张。
- 连续帧超时会记录待人工处理帧；合成前验证完整帧序列和文件存在性。

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

任务状态响应中的 `media` 字段只返回 `/api/v1/media/{media_id}` 形式的受控 URL，不向前端暴露结果文件的本地绝对路径。

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

历史响应不会暴露本地文件路径。图片历史项返回 `media_url`、`thumbnail_url` 和 `cover_url`，均指向受控媒体接口；视频历史项在视频封面闭合前暂不返回本地输出路径。

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
