# API 概览

统一前缀：`/api/v1`。

基础：

- `GET /health`
- `GET /models`
- `GET /config/status`
- `GET /settings`
- `PATCH /settings`

图片：

- `POST /image-jobs`
- `GET /image-jobs/{job_id}`
- `POST /image-jobs/{job_id}/pause`
- `POST /image-jobs/{job_id}/resume`
- `POST /image-jobs/{job_id}/cancel`

图片任务状态包含 `status`、`attempt_count`、安全错误摘要以及 `media`。`media` 只包含受控媒体 URL，不包含本地绝对路径。

业务错误使用统一响应：资源不存在为 `404 NOT_FOUND`，状态冲突为 `409 STATE_CONFLICT`，业务参数不合法为 `422 BUSINESS_VALIDATION_ERROR`。

视频：

- `POST /video-projects`
- `PATCH /video-projects/{project_id}/draft`
- `POST /video-projects/{project_id}/storyboard/generate`
- `POST /video-projects/{project_id}/storyboard/versions`
- `GET /video-projects/{project_id}/storyboard/versions`
- `POST /video-projects/{project_id}/storyboard/versions/{version_id}/confirm`
- `POST /video-projects/{project_id}/keyframes/generate`
- `GET /video-projects/{project_id}/keyframes`
- `POST /video-projects/{project_id}/keyframes/{frame}/regenerate`
- `POST /video-projects/{project_id}/keyframes/confirm`
- `POST /video-projects/{project_id}/frames/generate`
- `POST /video-projects/{project_id}/frames/{frame}/repair`
- `POST /video-projects/{project_id}/stitch`

历史与媒体：

- `GET /history`
- `GET /media/{media_id}`
- `DELETE /media/{media_id}?confirm=true`

历史响应不包含本地文件路径。图片历史项通过 `media_url`、`thumbnail_url` 和 `cover_url` 指向 `/api/v1/media/{media_id}`；视频历史项在封面闭合前不返回本地输出路径。
