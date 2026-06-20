# 架构说明

项目采用 FastAPI Web、独立 Worker、SQLite 和原生前端。

- `src/image_video/api/`：HTTP API。
- `src/image_video/application/`：应用服务和流程编排。
- `src/image_video/infrastructure/`：配置、数据库、供应商适配、日志。
- `src/image_video/worker/`：后台 Worker Runner、图片任务处理和进程入口。
- `frontend/`：中文本地前端页面。
- `scripts/`：安全扫描、旧数据迁移等操作脚本。
- `data/`：本地运行数据，不进入 Git。

数据库使用 SQLAlchemy 2 和 Alembic，SQLite 启用 WAL、foreign keys 和 busy timeout。

Matsca native 模式的同步图片结果可能返回官方图片资源 URL。项目在图片任务处理器层支持通过普通设置 `native_download_proxy` 为该下载阶段配置 HTTP/SOCKS 代理，以处理官方资源直连失败或 `403 Forbidden` 的情况。

普通图片任务由独立 Worker 消费。Worker 启动时恢复过期 lease，领取 `image.generate`，运行期间维持 heartbeat，并将明确失败写为 `failed`、上游超时写为 `needs_attention`。视频生成尚未迁入该 Worker，仍属于后续验收范围。

FastAPI 在 `/` 提供中文前端，在 `/assets` 提供静态资源。图片任务完成后，前端只使用 `/api/v1/media/{media_id}` 访问数据库登记且位于 `data/` 内的媒体文件。

视频连续帧调用 Matsca edits：首个中间帧使用起始锚点和最多 7 张用户参考图，后续帧使用结束锚点、上一帧和最多 6 张用户参考图。服务会跳过已有完整帧、记录不确定超时，并在 FFmpeg 合成前校验计划要求的每一帧及其本地文件。
