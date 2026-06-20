# 架构说明

项目采用 FastAPI Web、独立 Worker、SQLite 和原生前端。

- `src/image_video/api/`：HTTP API。
- `src/image_video/application/`：应用服务和流程编排。
- `src/image_video/infrastructure/`：配置、数据库、供应商适配、日志。
- `src/image_video/worker/`：后台 Worker 入口和任务处理。
- `frontend/`：中文本地前端页面。
- `scripts/`：安全扫描、旧数据迁移等操作脚本。
- `data/`：本地运行数据，不进入 Git。

数据库使用 SQLAlchemy 2 和 Alembic，SQLite 启用 WAL、foreign keys 和 busy timeout。

Matsca native 模式的同步图片结果可能返回官方图片资源 URL。项目在图片任务处理器层支持通过普通设置 `native_download_proxy` 为该下载阶段配置 HTTP/SOCKS 代理，以处理官方资源直连失败或 `403 Forbidden` 的情况。当前 Worker 入口仍是最小启动占位，完整队列消费循环需在后续验收中闭合。
