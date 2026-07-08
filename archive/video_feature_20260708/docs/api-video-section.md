# 视频 API 归档说明

默认 `VIDEO_FEATURE_ENABLED=false` 时，`/api/v1/video-projects` 及其旧子路径均返回：

```json
{
  "data": null,
  "error": {
    "code": "VIDEO_FEATURE_ARCHIVED",
    "message": "视频功能已归档，当前默认不可用；恢复请查看 archive/video_feature_20260708/restore-notes.md",
    "details": null
  },
  "request_id": "..."
}
```

HTTP 状态为 `410 Gone`。

完整视频 API 旧实现参考 `backend/api_video_projects.py.txt`。

