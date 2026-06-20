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
