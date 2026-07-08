# 归档文件清单

已复制到本目录：

- `backend/api_video_projects.py.txt`：完整视频 API router 参考。
- `backend/application_video_projects.py.txt`：视频项目应用服务、生成器和合成流程参考。
- `backend/worker_video_handler.py.txt`：视频 Worker handler 参考。
- `frontend/index_video_section.html`：旧视频项目前端 section 参考。
- `frontend/app_video_exports.md`：前端视频相关导出函数说明。
- `frontend/app_video_dom_bindings.md`：旧视频 DOM 绑定和默认 UI 入口说明。
- `tests/test_video_projects.py.txt`：旧视频项目单元测试参考。
- `tests/test_video_worker.py.txt`：旧视频 Worker 单元测试参考。
- `tests/video-test-notes.md`：视频测试恢复说明。
- `docs/api-video-section.md`：视频 API 归档说明。
- `docs/guide-video-section.md`：视频实现归档说明。
- `docs/plan-video-history-summary.md`：视频历史开发摘要。

未移动且必须保留在 active tree 的 migration：

- `migrations/versions/20260619_0003_video_projects.py`
- `migrations/versions/20260619_0004_video_keyframes.py`
- `migrations/versions/20260619_0005_video_frames.py`
- `migrations/versions/20260622_0006_video_upstream_tasks.py`
- `migrations/versions/20260627_0007_video_image_recovery_fields.py`

active tree 仍保留的兼容内容：

- SQLAlchemy video models：`VideoProject`、`VideoReferenceImage`、`VideoStoryboardVersion`、`VideoKeyframe`、`VideoFrame`。
- `HistoryService` 对旧视频记录、封面、输出路径和 storage estimate 的兼容读取。
- `PublicSettings.ffmpeg_path` 与 `cost_rates.video_per_frame` 兼容旧 `data/settings.json`。

约束：

- `archive/video_feature_20260708/**/*.py.txt` 只作为恢复参考。
- 主代码不得 import `archive/` 中任何内容。
- 默认 Ruff、pytest、pyright 和前端测试不得依赖 archive 中源码。

