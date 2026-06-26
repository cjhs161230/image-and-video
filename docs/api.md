# API 概览

统一前缀：`/api/v1`。响应不暴露本地绝对路径；业务错误统一映射为 `404 NOT_FOUND`、`409 STATE_CONFLICT` 或 `422 BUSINESS_VALIDATION_ERROR`。

## 基础与设置

- `GET /health`
- `GET /models`
- `GET /config/status`
- `GET /estimates/storage`
- `GET /settings`
- `PATCH /settings`

`/settings` 只处理公开设置：`ffmpeg_path`、`native_download_proxy`、`matsca_direct_concurrency`、`matsca_native_concurrency`、`cost_rates`。`cost_rates` 当前只接受 `image_per_image` 和 `video_per_frame`。

`/estimates/storage` 根据已登记且位于 `data/` 内的图片、视频帧和视频成品统计平均 MB；无样本时返回 `source=fallback` 并使用经验值。

## 统一任务

- `GET /jobs/{job_id}`
- `POST /jobs/{job_id}/pause`
- `POST /jobs/{job_id}/resume`
- `POST /jobs/{job_id}/cancel`

任务状态只返回任务 ID、类型、状态、尝试次数和安全错误摘要，不返回 payload。控制接口是状态机转换，不是强制覆盖：`pause` 只对 `queued/running` 生效，`resume` 对 `paused` 生效，也允许图片相关 `needs_attention` 重新排队以恢复下载或继续轮询，`cancel` 只对 `queued/running/paused/needs_attention` 生效；`completed` 等终态请求会返回当前状态而不改变任务。

## 图片

- `POST /image-jobs`
- `GET /image-jobs/{job_id}`
- `POST /image-jobs/{job_id}/pause`
- `POST /image-jobs/{job_id}/resume`
- `POST /image-jobs/{job_id}/cancel`

`POST /image-jobs` 支持 `model`、`prompt`、`n`、`size`、`quality`、`style`、`background`、`moderation`、`output_format`、`output_compression`、`input_fidelity`、`matsca_mode`、`input_media_ids`。

关键限制：

- `matsca_mode` 只接受 `direct|native`；`app` 返回 `422`。
- `n` 为 `1..4`。
- `size` 支持 `auto`、空值和任意正整数 `宽x高`。
- `quality` 支持 `auto|low|medium|high`，兼容旧别名 `standard -> medium`、`hd -> high`。
- `moderation` 支持 `auto|low`。
- `output_compression` 支持 `0..100`。
- `input_fidelity` 支持 `low|high`。
- `input_media_ids` 最多 8 个；Worker 校验单图 10 MB、总量 80 MB。

图片状态响应中的 `media` 只包含 `/api/v1/media/{media_id}` 形式的受控 URL。

图片任务控制接口与统一任务控制一致。当前前端会按任务状态隐藏不可用控制按钮；后端仍以状态机为最终约束。

Matsca 图片结果同时支持 `b64_json` 和 `url`。返回 URL 时，Worker 会先把 URL 恢复信息写入任务 payload，再下载图片；下载或保存失败进入 `needs_attention`，继续任务时优先只重新下载。

## 视频项目

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

草稿 API 支持 `title`、`description`、`start_frame`、`end_frame`、`total_frames`、`fps`、`reference_images`。当前前端不直接让用户填写帧号，而是按“视频时长（秒）+ 每秒帧数（FPS）”换算：`start_frame=0`、`total_frames=round(duration_seconds * fps)`、`end_frame=total_frames - 1`。

生成类接口只创建持久化任务并返回 `job_id` 与 `status=queued`：

- `storyboard/generate` -> `video.storyboard.generate`
- `storyboard/review` -> `video.storyboard.review`
- `keyframes/generate` -> `video.keyframes.generate`
- `keyframes/{frame}/regenerate` -> `video.keyframe.regenerate`
- `frames/generate` -> `video.frames.generate`
- `frames/{frame}/repair` -> `video.frame.repair`
- `stitch` -> `video.stitch`

`keyframes` 返回关键帧状态、帧号、时间点、描述、提示词和受控 `media_url`，供前端直接验收实际图片。`frames/issues` 返回缺失记录、缺失文件、失效或需人工处理的帧，并包含帧号、时间点、片段范围、提示词和安全错误摘要。`stitch` 合成静音 H.264/yuv420p MP4。`output` 只读取数据库登记且位于 `data/` 内的 MP4。视频项目删除需要 `confirm=true`，会删除数据库记录和项目登记文件；文件删除失败时返回 `partial_failed` 并保留记录。

视频关键帧、连续帧和补帧会保存稳定 `client_task_id`、上游任务 ID 和 URL 结果。已有上游任务 ID 时恢复继续轮询，已有 URL 时恢复只重新下载，不默认重新生成。

## 历史与媒体

- `GET /history`
- `GET /history?kind=image`
- `GET /history?kind=video`
- `POST /media/upload`
- `GET /media/{media_id}`
- `DELETE /media/{media_id}?confirm=true`

`POST /media/upload` 接收单张 PNG/JPEG/WebP 图片，限制 10 MB，返回受控 `media_id`、`url`、`width`、`height`。

历史响应不包含本地路径。图片历史项返回受控 `media_url`、`thumbnail_url`、`cover_url`；视频历史项使用首张已完成关键帧作为封面，并在存在安全成品 MP4 时返回 `/api/v1/video-projects/{project_id}/output`。图片媒体和视频项目都支持二次确认删除。
