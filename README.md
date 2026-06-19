# 图像与视频工作台

面向 Windows 本机单用户的 AI 图像生成与逐帧视频工作台。

项目正在按照 [`PLAN.md`](PLAN.md) 重建。当前计划状态为 `Active`，阶段 0–6 已完成验证；阶段 7“关键帧门禁”尚未开始。当前后端已具备基础 API、持久化队列、供应商适配、普通图片任务和视频分镜门禁能力，但前端、关键帧、连续帧、合成、旧数据迁移和启动脚本仍未完成，因此还不是最终可交付版本。

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

未完成：

- 关键帧生成、预览、指定重生成和关键帧确认门禁。
- 连续帧生成、缺帧恢复和 FFmpeg MP4 合成。
- 完整中文前端页面。
- 旧数据迁移。
- `start.bat` / `stop.bat`。
- 完整需求、架构、开发、API 和迁移文档。
- GitHub 私有仓库发布和旧项目归档。

## 安全说明

- API 密钥只允许写入本地 `.env`，不要提交 `.env`。
- 不要复制旧项目的 `.env` 或 `config.json`。
- 旧项目中曾明文保存过的 DashScope、Matsca、DeepSeek 凭证在确认轮换前，不能创建首个提交或推送。
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

## 配置

复制 `.env.example` 为 `.env`，只在 `.env` 中填写真实凭证。

支持的密钥和配置项包括：

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
- `DEEPSEEK_MODEL`

FFmpeg 默认路径：

```text
D:\ffmpeg\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe
```

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

## 固定产品约束

- 仅支持 Windows 本机单用户。
- Web 服务只监听 `127.0.0.1`。
- API 统一为 `/api/v1`，不保留旧 API。
- 不实现 Matsca 商用模式、音频、真正视频模型、远程访问、多用户、Linux/macOS 支持或 React/Vue 前端。
