# 开发指南

本文合并原需求、架构、开发、迁移和历史设计说明中的长期有效内容。当前进度以根目录 `PLAN.md` 为准，用户入口以 `README.md` 为准，API 细节见 `docs/api.md`。

## 产品边界

- Windows 本机单用户，Web 服务只监听 `127.0.0.1`。
- 后端使用 FastAPI、独立 Worker、SQLite、SQLAlchemy 2、Alembic。
- 前端使用原生 HTML/CSS/JavaScript，不引入 React/Vue。
- 图片和视频生成统一进入持久化任务队列，支持暂停、继续、取消、lease、heartbeat 和重启恢复。
- 视频流程依次经过草稿、分镜确认、关键帧确认、连续帧、合成；分镜和关键帧完成后必须等待用户确认。
- 不实现远程访问、多用户、Linux/macOS、音频、真正视频模型、旧 API 兼容或 GitHub Actions。

## 架构

- `src/image_video/api/`：HTTP API。
- `src/image_video/application/`：应用服务和流程编排。
- `src/image_video/infrastructure/`：配置、数据库、供应商适配、日志。
- `src/image_video/worker/`：Worker Runner、图片/视频任务处理和进程入口。
- `frontend/`：中文本地前端。
- `scripts/`：安全扫描、旧数据迁移和 Windows 启动辅助脚本。
- `data/`：数据库、日志、上传、生成媒体、迁移报告和 PID 文件，不进入 Git。

数据库启用 WAL、foreign keys 和 busy timeout。Web 请求、Worker 生命周期和供应商执行器分别写入 `data/logs/web.jsonl`、`worker.jsonl`、`provider.jsonl`，日志统一递归脱敏；Worker 对本地解析和校验异常会把安全摘要同步写入任务错误，避免只留下“任务处理失败”。

Worker 当前处理任务类型：`image.generate`、`video.storyboard.generate`、`video.storyboard.review`、`video.keyframes.generate`、`video.keyframe.regenerate`、`video.frames.generate`、`video.frame.repair`、`video.stitch`。任务运行中若被暂停或取消，处理器会在外部调用前后检查运行权，不覆盖用户控制状态。队列控制只会改变允许来源状态：暂停用于 `queued/running`，继续用于 `paused`，取消用于 `queued/running/paused/needs_attention`；图片相关 `needs_attention` 可继续重新排队以执行恢复下载或继续轮询；`completed`、`failed`、`cancelled` 等终态不会被控制接口改写。

## 供应商与配置

密钥只从 `.env` 读取；公开运行设置写入 `data/settings.json`。`.env.example` 当前包含：

- `IMAGE_VIDEO_HOST`
- `IMAGE_VIDEO_PORT`
- `DASHSCOPE_API_KEY`
- `MATSCA_DIRECT_BASE_URL`
- `MATSCA_DIRECT_API_KEY`
- `MATSCA_NATIVE_BASE_URL`
- `MATSCA_NATIVE_API_KEY`
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_API_KEY`
- `DEEPSEEK_MODEL`

公开设置包括 `ffmpeg_path`、`native_download_proxy`、`matsca_direct_concurrency`、`matsca_native_concurrency` 和 `cost_rates`。`cost_rates` 当前只接受 `image_per_image` 和 `video_per_frame`。

Matsca 当前只支持 `direct` 和 `native`：

- `direct` 使用异步 `/api/image-tasks/generations`、`/api/image-tasks/edits`、`/api/image-tasks`，默认请求 `b64_json`，结果同时兼容 `b64_json` 和 `url`；上游 task id 会持久化，Worker 重启后继续轮询原任务，不重新创建可能已计费请求。
- `native` 使用同步 `/v1/images/generations` 和 `/v1/images/edits`，默认请求 URL 结果；`native_download_proxy` 只用于下载返回的官方图片 URL。
- direct/native 每 Key 图片并发固定为 2。direct 异步任务从创建 task 到上游终态持续占用槽位，native 官方图片 URL 下载阶段不占用供应商图片任务槽。
- app、商用、stream、partial_images、variations、文本接口和 Responses API 当前不支持。

DashScope、Matsca 和 DeepSeek 的生产请求都通过凭证级 `CredentialGate` 与 `ProviderRequestExecutor`。429 遵循 `Retry-After`，5xx 和连接错误有限重试；已发送但未确认的超时进入 `needs_attention`。Matsca URL 结果会先写入任务或帧记录，再下载；下载或本地保存失败会单独归类，并保留恢复信息用于只重新下载。

## 视频实现要点

- DeepSeek 分镜规划与独立复审会接收帧范围、FPS 和参考图文字标注；复审保存新的 AI 版本，但不自动确认。
- 分镜计划统一校验：首个关键帧必须为 0，关键帧递增且不重复，片段结束帧大于开始帧，片段边界对应关键帧，并按关键帧连续衔接。
- 关键帧生成和指定重生成使用持久化任务；每帧保存稳定 `client_task_id`、上游 task id 和 URL 结果，指定关键帧重生成只使相邻片段已有连续帧变为 `invalid`，并清除旧视频输出路径。
- 连续帧片段内顺序生成，片段间并行；首个中间帧使用起始锚点和最多 7 张用户参考图，后续帧使用结束锚点、上一帧和最多 6 张用户参考图。生产 Worker 使用 Matsca direct 异步编辑任务，并保存 `VideoFrame.client_task_id`、`VideoFrame.upstream_task_id` 和 `VideoFrame.result_url` 以支持失败后恢复同一上游任务或只重新下载；如果上游提示服务重启导致图片任务中断，则用相同 `client_task_id` 自动重新提交该帧并保存新的上游任务 id。
- 缺失记录、缺失文件、失效帧和 `needs_attention` 帧可通过单帧修复任务补生成；已有 `result_url` 时修复只重新下载。
- FFmpeg 合成前校验完整帧序列和文件存在性，输出静音 H.264/yuv420p MP4；连续帧完成后幂等入队 `video.stitch`。
- 视频历史封面使用首张已完成关键帧，通过受控接口读取；视频成品 MP4 通过受控 `output` 接口读取，视频项目支持二次确认删除。

## 前端与媒体安全

FastAPI 在 `/` 提供中文前端，在 `/assets` 提供静态资源。前端包含图片工作台、视频项目、历史和设置四个工作区。当前前端以单页方式实现专属页面切换：右上角文字导航切换可见工作区，URL hash 可保持当前页面。设置页提供 `深色默认` 和 `清爽浅色` 两种界面背景，选择只写入浏览器 `localStorage`，不进入后端设置 API。

视频项目表单面向用户显示“视频时长（秒）+ 每秒帧数（FPS）”，前端自动换算为后端草稿 API 使用的 `start_frame=0`、`total_frames` 和 `end_frame`。这样用户不需要手算帧号，同时保持后端分镜、关键帧、连续帧流程继续使用帧范围。

视频参考图区域默认收起，按钮旁显示当前参考图数量；展开后保留上传、标签和备注能力，收起不会清空已选文件或已上传引用。分镜生成或 AI 复审完成后，前端会在“分镜结果”区自动加载最新分镜版本，并同时显示可读分镜看板和可编辑 JSON；用户也可以点击版本按钮切换历史版本。关键帧结果区直接显示帧号、时间点、描述、提示词和实际图片；连续帧检查区显示问题帧、时间点、原因和修复入口。视频任务失败或进入 `needs_attention` 时，前端会把任务的 `error_message` 显示在“任务失败原因”位置，避免只看到 `failed` 状态。

历史页的视频部分是项目历史：`draft`、待确认、生成中、失败和完成的视频项目都会显示。点击“进入项目”会切回视频工作台，恢复项目 ID、表单摘要、分镜版本、关键帧和连续帧问题；不会自动重新提交任何生成任务。

图片图生图和视频参考图上传先走本地上传接口，上传 PNG/JPEG/WebP 到 `data/uploads/` 并登记为 `MediaAsset`。后续图片任务和视频草稿只传递 `media_id`，不暴露本地路径或浏览器临时文件。

媒体读取、图片删除、视频成品读取和视频项目删除必须满足两个条件：数据库已登记，且文件位于配置的 `data/` 根目录内。路径越界时不得删除文件，并保留记录供人工处理。

前端会读取 `cost_rates`、浏览器 `navigator.storage.estimate()` 和 `/api/v1/estimates/storage` 做本地积分/磁盘提示；有真实产物样本时优先使用真实平均值，无样本时回退经验值。图片和视频任务控制按钮会按状态显示：`queued/running` 可暂停或取消，`paused` 可继续或取消，终态隐藏控制按钮；后端控制接口仍对终态任务保持 no-op，不会把 `completed` 改回其他状态。

## 启动、迁移与验证

启动：

```powershell
start.bat
```

默认地址为 `http://127.0.0.1:17860`。如端口被占用，在 `.env` 中设置 `IMAGE_VIDEO_PORT`；`IMAGE_VIDEO_HOST` 应保持 `127.0.0.1`。停止：

```powershell
stop.bat
```

旧数据迁移：

```powershell
python scripts\migration\migrate_legacy.py <legacy_root> <legacy_database>
```

迁移使用 SQLite backup API 创建只读快照，不修改旧库；复制可定位媒体，计算大小和 SHA-256，缺失媒体标记为 `missing`，旧密钥配置不会导入。

常用验证：

```powershell
uv --cache-dir .uv-cache run pytest -q --basetemp=data\test-tmp
uv --cache-dir .uv-cache run ruff check .
uv --cache-dir .uv-cache run pyright
npm run lint
npm run format:check
npm run test:e2e
python scripts\security\scan_secrets.py .
```

`npm run test:e2e` 当前是 Node 侧静态页面/API 客户端测试，不是真实浏览器端到端验收。真实上游验收必须由用户明确授权。2026-06-24 已执行一次获授权的小样本直连视频 smoke：DeepSeek 分镜和 Matsca direct 关键帧成功，连续帧任务失败，未生成 MP4；本地已修复连续帧生产 Worker 接线，仍需重启后重新验收。

## 当前已知缺口

- 最终全量验证和秘密扫描需要在每轮可交付前重新运行。
- 真实浏览器端到端验收尚未执行；当前 `npm run test:e2e` 仍是 Node 静态/API 客户端测试。
- 完整 DeepSeek/Matsca/FFmpeg 付费 smoke 尚未通过；最近一次小样本直连测试停在连续帧 `HTTPSTATUSERROR`。
