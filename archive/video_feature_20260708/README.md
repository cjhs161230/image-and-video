# 视频功能归档说明

本目录保存 2026-07-08 视频功能归档参考资料。

当前项目默认定位为图片生成工作台。视频功能状态为已归档 / 默认停用 / 可恢复，默认开关为 `VIDEO_FEATURE_ENABLED=false`。

默认关闭时：

- 后端只挂载轻量归档 router：`src/image_video/api/video_projects_archived.py`。
- 完整视频 router、DeepSeek 视频规划、Matsca 视频关键帧、Matsca 连续帧、FFmpeg 合成链路不初始化。
- Worker 默认只注册 `image.generate`，不领取 `video.*` queued job。
- 前端不展示视频项目入口。

本目录中的 `.py.txt` 文件只作恢复参考，主代码不得 import `archive/` 中任何内容。

