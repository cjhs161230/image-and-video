# API 概览

统一前缀：`/api/v1`。响应不暴露本地绝对路径；业务错误统一使用 envelope：

```json
{
  "data": null,
  "error": {"code": "...", "message": "...", "details": null},
  "request_id": "..."
}
```

## 基础与设置

- `GET /health`
- `GET /models`
- `GET /config/status`
- `GET /estimates/storage`
- `GET /settings`
- `PATCH /settings`

`/settings` 只处理公开设置：`ffmpeg_path`、`native_download_proxy`、`matsca_direct_concurrency`、`matsca_native_concurrency`、`cost_rates`。`ffmpeg_path` 和 `cost_rates.video_per_frame` 属于归档视频兼容字段，保留旧 `data/settings.json` 可加载能力。

## 统一任务

- `GET /jobs/{job_id}`
- `POST /jobs/{job_id}/pause`
- `POST /jobs/{job_id}/resume`
- `POST /jobs/{job_id}/cancel`

默认 Worker 只领取 `image.generate`。旧 `video.*` queued job 默认留在队列中，不领取、不失败、不取消。

## 图片

- `POST /image-jobs`
- `GET /image-jobs/{job_id}`
- `POST /image-jobs/{job_id}/pause`
- `POST /image-jobs/{job_id}/resume`
- `POST /image-jobs/{job_id}/cancel`

`POST /image-jobs` 支持 `model`、`prompt`、`n`、`size`、`quality`、`style`、`background`、`moderation`、`output_format`、`output_compression`、`input_fidelity`、`matsca_mode`、`input_media_ids`。

`matsca_mode` 只接受 `direct|native`；`app` 返回 `422`。图片状态响应中的 `media` 只包含 `/api/v1/media/{media_id}` 形式的受控 URL；`result_urls` 返回已持久化的上游图片 URL，用于排查取回问题。

## 视频项目归档接口

默认 `VIDEO_FEATURE_ENABLED=false` 时，以下接口保留路径但不提供视频生成、编辑、确认、修复、合成或删除能力，统一返回 `410 VIDEO_FEATURE_ARCHIVED`：

- `POST /video-projects`
- `GET /video-projects/{project_id}`
- `PATCH /video-projects/{project_id}/draft`
- `POST /video-projects/{project_id}/storyboard/generate`
- `POST /video-projects/{project_id}/storyboard/review`
- `POST /video-projects/{project_id}/storyboard/versions`
- `GET /video-projects/{project_id}/storyboard/versions`
- `POST /video-projects/{project_id}/storyboard/versions/{version_id}/confirm`
- `POST /video-projects/{project_id}/keyframes/generate`
- `GET /video-projects/{project_id}/keyframes`
- `GET /video-projects/{project_id}/keyframes/{frame}/media`
- `GET /video-projects/{project_id}/output`
- `POST /video-projects/{project_id}/keyframes/{frame}/regenerate`
- `POST /video-projects/{project_id}/keyframes/confirm`
- `POST /video-projects/{project_id}/frames/generate`
- `GET /video-projects/{project_id}/frames/issues`
- `POST /video-projects/{project_id}/frames/{frame}/repair`
- `POST /video-projects/{project_id}/stitch`
- `DELETE /video-projects/{project_id}?confirm=true`

错误响应：

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

## 历史与媒体

- `GET /history`
- `GET /history?kind=image`
- `GET /history?kind=video`
- `POST /media/upload`
- `GET /media/{media_id}`
- `DELETE /media/{media_id}?confirm=true`

历史响应不包含本地路径。图片历史项返回受控 `media_url`、`thumbnail_url`、`cover_url`。旧视频历史项只做归档兼容展示，`can_continue=false`，不引导继续视频流程。
