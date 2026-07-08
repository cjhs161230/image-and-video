# 视频测试恢复说明

归档测试文件：

- `test_video_projects.py.txt`
- `test_video_worker.py.txt`

这些文件保留旧视频项目服务和视频 Worker 的回归覆盖。恢复视频功能时，可按需复制回 `tests/unit/` 并改回 `.py`，但必须同步确认：

- `VIDEO_FEATURE_ENABLED=true` 时完整 router 挂载。
- Worker 注册 `video.*` handler。
- 默认 `VIDEO_FEATURE_ENABLED=false` 时 `video.*` job 仍不被领取。
- archive 目录中的 `.py.txt` 不被默认 pytest 收集。

