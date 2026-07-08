# 视频实现归档说明

视频实现曾覆盖：

- 草稿和最多 8 张带文字标注参考图。
- DeepSeek 分镜规划和 AI 复审。
- 关键帧生成、指定关键帧重生成和相邻片段失效。
- 连续帧生成、缺帧修复和上游任务恢复。
- FFmpeg 静音 H.264/yuv420p MP4 合成。
- 历史封面、成品受控访问和二次确认删除。

当前这些能力已归档 / 默认停用 / 可恢复。默认 Worker 只处理 `image.generate`。

兼容保留：

- video SQLAlchemy models。
- video Alembic migration。
- `ffmpeg_path` 和 `cost_rates.video_per_frame` 设置字段。
- history 对旧视频记录的只读兼容。

