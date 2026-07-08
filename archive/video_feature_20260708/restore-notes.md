# 视频功能恢复说明

恢复视频功能前先确认用户明确需要恢复，并确认真实付费 smoke 是否授权。

恢复步骤：

1. 在本地环境中设置 `VIDEO_FEATURE_ENABLED=true`。
2. 确认 `src/image_video/main.py` 在开启分支挂载完整 `video_projects_router`，且不要同时挂载 archived router。
3. 确认 `src/image_video/worker/main.py` 在开启分支注册 `video.storyboard.generate`、`video.storyboard.review`、`video.keyframes.generate`、`video.keyframe.regenerate`、`video.frames.generate`、`video.frame.repair`、`video.stitch`。
4. 恢复前端视频导航和视频 section，可参考 `frontend/index_video_section.html`、`frontend/app_video_exports.md`、`frontend/app_video_dom_bindings.md`。
5. 保留并重新运行全部 Alembic migration，特别是现有 video migration。
6. 运行 Python、Node 和前端静态测试。
7. 真实 DeepSeek / Matsca / FFmpeg smoke 必须单独取得用户授权，不能默认执行。

恢复时优先使用 active tree 中保留的原始视频代码和 migration；archive 中 `.py.txt` 只作比对和恢复参考。

