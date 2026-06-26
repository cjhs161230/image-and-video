# 图像与视频工作台重建与迁移执行计划

**状态：** Active  
**版本：** 1.5
**基准日期：** 2026-06-19  
**最近审计：** 2026-06-24
**接入基准：** 2026-06-21 Matsca 最新接入文档
**目标目录：** `E:\auxiliary tool\image-and-video`  
**目标仓库：** GitHub 私有仓库 `image-and-video`

本文件是唯一有效执行计划。执行过程中只允许更新既有步骤的状态；目标、范围、步骤、优先级、验证方法、风险或下一步如需变化，必须先取得用户明确批准。

## 真实进度审计结论

按“生产代码已接线、产品入口可操作、自动测试覆盖关键行为、必要运行证据存在”核对后，当前可确认：

- FastAPI、独立 Worker、SQLite/Alembic、持久化任务队列、普通图片任务、本地媒体保存和受控访问已形成可测试闭环。
- 视频分镜、关键帧、连续帧、补帧和合成已有持久化任务处理器；片段内顺序、片段间并行、上一帧落盘后再生成下一帧已有回归测试。
- 统一任务 API、视频项目基础 API、图片/视频历史列表、启动/停止脚本和旧数据迁移已有实现。
- Matsca direct/native 生产调用已接入凭证级并发门、分类重试和上游 task id 恢复；app 运行能力已移除。
- 视频处理器已增加运行权检查，暂停或取消后不会登记媒体、推进项目状态或自动入队后续任务。
- 图片图生图、视频最多 8 张参考图上传、视频时长+FPS 前端换算、DeepSeek 独立复审、结构化日志、前端成本提示、前端专属页面切换和本地浅色主题已实现。
- 2026-06-21 曾完成 pytest 109 项、Ruff、Pyright、ESLint、Prettier、Node 前端测试和秘密扫描；后续阶段又完成多组聚焦测试。

当前仍不能确认完成：

- 当前 `npm run test:e2e` 是 Node 静态/API 客户端测试，不是真实浏览器端到端验收。
- 当前节点不执行真实付费 smoke；真实上游验收需用户单独授权。

因此计划保持 `Active`。所有上述缺口修复并重新验收前，不得标记 `Completed`。

## 目标与固定决策

- 建立 Windows 专用、仅监听 `127.0.0.1` 的本地图像与视频工作台。
- 使用 FastAPI Web + 独立 Worker + SQLite 持久化队列。
- 使用 `src/image_video` 包结构、SQLAlchemy 2、Alembic、uv、原生 HTML/CSS/ES Modules。
- 保留四个 DashScope/Wan/Qwen 模型，新增 GPT-Image-2；Matsca 当前只支持 `direct/native`。
- 图片和视频统一进入持久化任务系统，支持暂停、继续、取消和重启恢复。
- 视频流程在分镜和关键帧完成后分别暂停，用户确认后继续。
- 中间帧连续性优先：片段内顺序生成，片段间并行。
- Matsca direct/native 使用独立 Key；普通客户每 Key 图片并发固定为 2。
- Matsca direct 的普通图片、关键帧、指定关键帧重生成、连续帧和补帧全部使用异步图片任务并持久化上游 task id。
- Matsca native 使用同步 generations/edits 并请求 URL 结果；代理只允许用于下载返回的官方图片 URL。
- 前端按视频时长（秒）和 FPS 填写视频长度，自动换算为后端帧范围；FPS 为 1-60，总帧数无硬上限，但必须进行积分、磁盘和分级确认。
- 用户可上传最多 8 张参考图并标注角色、场景或风格；DeepSeek 只读取文字标注。
- FFmpeg 使用 `D:\ffmpeg\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe`，输出静音 H.264/yuv420p MP4。
- API 统一为 `/api/v1`，不保留旧 API。
- 密钥只从 `.env` 读取，普通设置写入 Git 忽略的 `data/settings.json`。
- 运行数据全部位于 Git 忽略的 `data/`。
- 旧项目已按计划归档到 `E:\auxiliary tool\archives\wan-image-viewer`。

## 核心接口与状态

接口资源包括健康检查、配置状态、模型、设置、图片任务、视频项目、参考图、分镜、关键帧、任务控制、历史和受控媒体访问。所有生成请求只创建持久化任务，由 Worker 执行。API 详情见 `docs/api.md`。

视频主状态：

```text
draft -> planning -> awaiting_storyboard_approval
-> generating_keyframes -> awaiting_keyframe_approval
-> generating_frames -> stitching -> completed
```

辅助状态：`paused`、`cancelled`、`failed`、`needs_attention`。上游请求超时视为结果不确定，进入 `needs_attention`，不得自动重发。

## 执行阶段

### 阶段 0：安全阻塞项与计划落盘

- [x] 将本计划写入目标根目录并标记为 `Active`。
- [x] 用户轮换旧项目中曾明文保存的 DashScope、Matsca 和 DeepSeek 凭证。
- [x] 不复制旧 `.env`、`config.json`、虚拟环境或缓存。
- [x] 检查 uv、Node、npm、Git、GitHub CLI 和 FFmpeg（`gh` 未安装，记录为阶段 13 前置项）。
- [x] 创建秘密扫描器并以测试驱动验证。
- [x] 当前工作区安全扫描通过；凭证轮换确认前不提交或推送。

### 阶段 1：项目骨架与版本管理

- [x] 建立规定目录结构、`pyproject.toml`、uv 锁文件和前端工具配置。
- [x] 创建完整 `.gitignore`、`.env.example` 和英文 `AGENTS.md`。
- [x] 初始化本地 Git；在凭证轮换和扫描通过后创建首个提交。

### 阶段 2：配置、日志与基础 API

- [x] 实现安全配置、普通设置、FFmpeg/代理/费率/并发配置。
- [x] 实现结构化脱敏日志和统一 API 响应。
- [x] 实现健康检查、配置状态、模型和设置 API。

### 阶段 3：数据库、Alembic 与持久化队列

- [x] 建立 SQLAlchemy 模型和 Alembic migration。
- [x] 启用 WAL、foreign keys、busy timeout。
- [x] 实现原子领取、lease、heartbeat、暂停、继续、取消和重启恢复。
- [x] 已发送但未确认的请求恢复为 `needs_attention`。

### 阶段 4：供应商适配层

- [x] 迁移 DashScope 四模型。
- [x] 实现 Matsca direct/native generations/edits、异步恢复、Base64/URL 和原生代理。
- [x] 实现 DeepSeek 规划、复审和有限重试。
- [x] 实现凭证级全局渐进并发、抖动、退避和错误分类。

### 阶段 5：普通图片任务

- [x] 支持四个旧模型和 GPT-Image-2 文生图/图生图。
- [x] 支持 1-4 张输出、最多 8 张输入和 PNG/JPEG/WebP。
- [x] 保存媒体、缩略图和元数据。

### 阶段 6：视频项目与分镜门禁

- [x] 实现草稿自动保存和最多 8 张带文字标注的参考图。
- [x] DeepSeek 生成关键帧与片段运动计划并严格校验。
- [x] 分镜后暂停；支持表单编辑、版本记录、AI 建议和用户确认应用。

### 阶段 7：关键帧门禁

- [x] 生成、预览和指定重生成 PNG 关键帧。
- [x] 关键帧变更只使相邻片段失效。
- [x] 关键帧完成后暂停，等待用户批准。

### 阶段 8：连续帧、恢复和合成

- [x] 片段内顺序、片段间并行生成。
- [x] 第一中间帧使用锚点加最多 7 张用户参考图；后续帧使用锚点、上一帧加最多 6 张用户参考图。
- [x] 支持缺失/失效帧补生成和超时人工处理。
- [x] 无缺帧后自动合成静音 H.264/yuv420p MP4。
- [x] 帧编号支持超过 999。

### 阶段 9：统一历史与媒体安全

- [x] 实现图片/视频统一历史、筛选、缩略图、封面和日志摘要。
- [x] 媒体访问仅允许数据库登记且位于 `data/` 内的文件。
- [x] 二次确认后删除记录和文件；部分失败必须可恢复。
  - 证据：图片媒体和视频项目均支持二次确认删除；视频删除仅处理数据库登记且位于 `data/` 内的项目文件，部分失败保留记录。

### 阶段 10：前端

- [x] 建立图片工作台、视频项目、历史、设置四个中文页面。
- [x] 展示阶段和帧级统计，支持任务控制和两次人工门禁。
  - 证据：项目摘要、帧问题、统一任务按钮、两次门禁、终态控制按钮隐藏和视频任务终态自动刷新已有前端测试覆盖。
- [x] 实现积分/磁盘估算和分级确认。
  - 证据：前端读取普通设置费率、浏览器磁盘空间和 `/api/v1/estimates/storage`；后端基于已登记真实产物统计平均大小，无样本时回退经验值。
- [x] 设置页只显示凭证配置状态。

### 阶段 11：旧数据迁移

- [x] 使用 SQLite backup API 创建只读快照，不修改旧库。
- [x] 根据每条记录的 `save_path` 和 `url_path` 定位真实媒体。
- [x] 复制媒体并计算大小和 SHA-256；缺失媒体标记 `missing`。
- [x] 归档旧日志但不导入旧密钥配置。
- [x] 生成可审计、可重复运行的迁移报告。

### 阶段 12：启动、停止与文档

- [x] `start.bat` 检查依赖、migration、FFmpeg，启动 Web/Worker 并打开浏览器。
  - 说明：脚本读取 `IMAGE_VIDEO_HOST` / `IMAGE_VIDEO_PORT`，默认绑定 `127.0.0.1:17860`，启动前检查端口占用；默认使用 Git 忽略的 `data\uv-cache`。
- [x] `stop.bat` 只停止 PID 文件记录的本项目进程。
- [x] 完成中文 README、需求、架构、开发、API 和迁移文档。
- [x] 压缩文档结构，合并过期/重复 docs 内容到 `README.md`、`PLAN.md`、`docs/guide.md` 和 `docs/api.md`。

### 阶段 13：验证、GitHub 私有仓库和旧项目归档

- [x] 通过 Ruff、Pyright、pytest、ESLint、Prettier 和基础前端 API/E2E。
  - 历史说明：2026-06-21 全量 pytest 109 项通过；Ruff、Pyright、ESLint、Prettier、Node 前端测试和秘密扫描通过。当前前端测试不包含真实浏览器自动化。
- [ ] 显式运行低成本 DeepSeek/Matsca/FFmpeg smoke test。
  - 2026-06-24 用户已授权小样本真实付费测试；已用直连模式创建 1 秒 / 10 FPS / 10 帧视频项目 `c94552e8-2871-46f0-8813-664bb1e17f50`。
  - 本轮结果：DeepSeek 分镜任务完成，Matsca direct 关键帧任务完成并生成第 0 帧和第 9 帧；连续帧任务 `video.frames.generate` 失败，错误码 `HTTPSTATUSERROR`，8 张中间帧仍为 `pending`，未触发成功合成，`/output` 返回 404。
  - 发现：连续帧真实运行路径曾未按计划持久化 direct edit 上游 task id，失败后不能恢复同一上游任务；分镜内容也未严格遵循用户提交的杯子测试描述。2026-06-24 已修复生产 Worker 连续帧接线，使其使用 direct 异步任务并持久化上游 task id；完整 DeepSeek/Matsca/FFmpeg smoke 仍需重启后重新验收，当前仍未通过。
- [x] 再次秘密扫描并检查 Git 暂存内容。
- [x] 创建并推送 GitHub 私有仓库 `image-and-video`。
- [ ] 最终启动验收后把计划标记 `Completed`。
- [x] 验证绝对路径后将旧项目移动到统一归档目录，不删除。

### 阶段 14：审计后基础闭环修复

- [x] 修复媒体原图和缩略图的统一 data 根目录校验，阻止越界读取或删除。
- [x] 为资源不存在、状态冲突和业务输入错误建立统一 API 错误响应。
- [x] 实现普通图片任务 Worker 消费、lease 恢复、心跳、失败分类和安全停止。
- [x] 处理运行中暂停/取消与任务完成之间的竞态，不覆盖用户控制状态。
- [x] 将中文前端挂载到 FastAPI，并闭合图片提交、轮询、控制和结果展示。
- [x] 使用本地模拟供应商完成普通图片任务端到端验收，不调用付费 API。
- [x] 更新 README 和架构/开发文档，使描述与实际能力一致。

### 阶段 15：Matsca 最新文档对齐

- [x] 完全移除 Matsca app 的枚举、API 类型、Worker 分支、凭证/环境变量、配置状态、并发设置、前端选项、测试和当前支持声明。
- [x] 兼容旧 `data/settings.json` 中的废弃 app 字段：读取时安全忽略，保存时不再写回。
- [x] direct 文生图使用 `POST /api/image-tasks/generations`，direct 图生图使用 `POST /api/image-tasks/edits`，统一通过 `GET /api/image-tasks?ids=...` 查询并请求 `b64_json`。
- [x] direct 普通图片、关键帧、指定关键帧重生成、连续帧和补帧均持久化上游 task id；Worker 重启后继续轮询原任务，禁止重新创建可能已计费任务。
- [x] native 文生图/图生图使用同步 `/v1/images/generations` 与 `/v1/images/edits` 并请求 `url`；`native_download_proxy` 只用于结果 URL 下载。
- [x] 为 `VideoKeyframe`、`VideoFrame` 增加可空 `upstream_task_id`，创建并验证 Alembic migration。
- [x] direct/native 每 Key 图片并发限制均为 2，并将凭证级全局并发门接入真实生产 Provider；direct 异步槽保持到任务终态。
- [x] 支持并校验 `moderation`、`output_compression`、`input_fidelity`、任意正整数尺寸/`auto`、输出 1-4 张、最多 8 张上传、单图 10 MB、总量 80 MB 和 10 分钟超时。
- [x] 429 遵循 `Retry-After`；5xx 和连接错误有限重试；请求已发送后的超时进入 `needs_attention` 且不得自动重发；识别 `upstream_direct_unavailable`。
- [x] 修复分镜、关键帧、指定关键帧重生成、连续帧、补帧和 FFmpeg 合成的暂停/取消竞态。
- [x] 同步更新前端、README、架构、API、`.env.example` 和自动测试。
- [ ] 运行 direct/native 聚焦测试、全量验证和秘密扫描；低成本真实 smoke 仅在用户明确授权后执行。
  - 2026-06-24 已获用户授权并执行一次 direct 视频小样本真实 smoke；结果见阶段 13，连续帧失败，完整链路未通过。

## 2026-06-23 后续开发计划 B

- [x] 按代码和自动测试重新核对参考图上传、图生图入口、FPS/总帧保存和视频上游请求恢复，清除文档中的过期缺口。
- [x] 恢复损坏的 Python `.venv` 和缺失的 Node 开发依赖，不修改锁文件。
- [x] 将 `JsonlLogger` 接入 Web、Worker 和供应商调用；历史摘要改为使用真实任务事件和安全错误信息；补齐普通设置校验。
- [x] 将 DashScope、DeepSeek 接入生产 `CredentialGate` / `ProviderRequestExecutor`；分镜请求传入帧范围、FPS 和参考图文字标注。
- [x] 新增持久化 `video.storyboard.review` 任务与 `POST /api/v1/video-projects/{id}/storyboard/review`，保存 AI 复审版本并继续由用户确认应用。
- [x] 实现视频草稿 800ms 防抖自动保存；关键帧重生成后将相邻片段帧真实标记为 `invalid`；补帧完成后恢复 `completed`；自动合成任务保持幂等。
- [x] 新增视频成品受控访问、视频项目二次确认删除、基于真实产物的估算 API、历史视频播放/删除和任务终态自动刷新。
- [x] 运行 pytest、Ruff、Pyright、ESLint、Prettier、Node 前端测试和秘密扫描；不运行任何真实付费 smoke。
- [x] 审计并压缩 README/PLAN/docs 文档结构，减少重复和过期专题文件。
- [x] 更新 `AGENTS.md` 启动排查排除规则和临时验证产物清理规则，减少无效上下文占用并保护正式回归测试。
- 工作区仍包含大量未提交的持续开发成果；不得 reset、clean、restore、覆盖或丢弃，且未经用户要求不得 commit/push/pull/切换分支。

## 2026-06-24 图片生成链路优先核对与最小修复计划

本轮先不推进视频缺口，优先确认普通图片生成链路是否按 `喵哥生图接入文档.txt` 正确构造 Matsca 请求体。当前没有 VPN/网络条件，不执行真实 Matsca/DeepSeek 付费 smoke，不读取 `.env`，只做离线请求体测试、本地模拟和必要的最小代码修正。

执行前必须保留以下事实和边界：

- `PLAN.md` 状态仍为 `Active`、版本 `1.5`，本文件仍是唯一进度来源。
- 工作区已有大量未提交改动，必须保护现有改动，不做 `reset`、`clean`、`restore`、提交、推送、拉取、合并、变基或切分支。
- 项目边界保持 Windows 本机单用户、FastAPI + 独立 Worker + SQLite/Alembic、原生 HTML/CSS/JavaScript、统一 `/api/v1`。
- `README.md` 与本计划当时声明保持：普通图片任务闭环已实现；视频分镜、关键帧、连续帧、补帧、合成已有基础链路；视频成品受控访问、视频项目删除、真实产物估算、视频终态自动刷新当时仍未完成，现已在后续小节闭合。
- 当前 `npm run test:e2e` 是 Node 静态/API 客户端测试，不是真实浏览器 E2E。
- 不清理不确定归属文件，例如 `.npm-cache/`；只允许清理本次会话创建且确认可再生成的临时验证产物和安全白名单缓存。

已知代码入口和测试入口：

- Matsca provider：`src/image_video/infrastructure/providers/matsca.py`
- 图片任务提交：`src/image_video/application/image_jobs.py`
- 图片 Worker：`src/image_video/worker/image_handler.py`
- Provider 单元测试：`tests/unit/test_matsca_provider.py`
- 图片任务单元测试：`tests/unit/test_image_jobs.py`
- 图片 Worker 单元测试：`tests/unit/test_image_worker.py`
- 图片相关集成测试：`tests/integration/test_base_api.py`

Matsca 图片请求体核对基准：

- direct 文生图：`POST /api/image-tasks/generations`，JSON，`model=gpt-image-2`，`response_format=b64_json`。
- direct 图生图：`POST /api/image-tasks/edits`，multipart，文件字段名 `image`，最多 8 张，`response_format=b64_json`。
- native 文生图：`POST /v1/images/generations`，JSON，`response_format=url`。
- native 图生图：`POST /v1/images/edits`，multipart，文件字段名 `image`，`response_format=url`。
- 查询异步任务：`GET /api/image-tasks?ids=...`。
- 离线测试应明确断言 `Authorization: Bearer ...`、`client_task_id`、`prompt`、`size`、`quality`、`style`、`background`、`moderation`、`output_format`、`output_compression`、`input_fidelity`、`n` 和 `response_format`。

执行步骤：

- [x] 最小重读 `AGENTS.md`、`PLAN.md`、`README.md`、`喵哥生图接入文档.txt`、三个图片链路代码文件和相关测试，确认本计划不与最新用户指令冲突。
- [x] 先加固 `tests/unit/test_matsca_provider.py` 离线测试，覆盖 direct/native 文生图、direct/native 图生图和异步任务查询的 URL、headers、JSON/multipart 字段和值。
- [x] 运行新增或加固后的 provider 测试，确认新增断言能暴露缺口；若新增断言已通过，则记录现有实现与接入文档一致，不为制造改动而改生产代码。
- [x] 若测试发现代码与接入文档不一致，只做最小修复；本轮新增 provider 断言通过，未发现需要修改生产代码的请求体不一致。
- [x] 运行聚焦验证：`uv --cache-dir .uv-cache run pytest -q tests/unit/test_matsca_provider.py tests/unit/test_image_jobs.py tests/unit/test_image_worker.py`。
- [x] 如图片 API 行为受影响，运行：`uv --cache-dir .uv-cache run pytest -q tests/integration/test_base_api.py`；本轮未改生产 API 行为，未运行该集成测试。
- [x] 对改动文件运行 Ruff；本轮未改生产代码或类型接口，未运行 `uv --cache-dir .uv-cache run pyright`。
- [x] 检查是否需要同步 README 或 docs；本轮只是离线测试加固且用户可见行为不变，README 和 docs 不需要更新。
- [x] 按本项目规则同步本小节执行状态；不得改变计划目标、范围、优先级或视频缺口含义。

## 2026-06-24 前端专属页面切换与清淡背景主题

- [x] 将首页四个功能区改为单页专属页面切换：右上角文字导航切换可见页面，支持 URL hash 刷新保持页面，并高亮当前入口。
- [x] 在设置页增加界面背景选择，默认深色，新增 `清爽浅色`，主题仅保存到浏览器 `localStorage`，不写入后端设置 API。
- [x] 补齐 Node 前端静态和客户端测试，验证导航标识、页面归一化、主题归一化和本地存储读写。
- [x] 运行 `npm run test:e2e`、`npm run lint`、`npm run format:check`；未改后端，未运行 Python 测试。
- [x] 为前端 CSS/JS 增加版本查询参数，避免浏览器继续使用旧静态资源缓存。

## 2026-06-24 文档真实状态同步

- [x] 按当前实现同步 README、开发指南和 API 文档：任务控制是真实状态机转换，但终态任务不会被暂停、继续或取消改写。
- [x] 明确前端页面切换、清爽浅色主题和静态资源缓存处理已实现。
- [x] 当时保持视频成品受控访问、视频删除、真实产物估算、视频终态自动刷新、图片终态控制按钮隐藏/禁用和真实浏览器 E2E 为未完成或未实测项；其中除真实浏览器 E2E 外，其余缺口已在后续小节闭合。

## 2026-06-24 项目剩余功能闭环

- [x] 前端图片和视频任务控制按钮按状态显示：`queued/running` 可暂停或取消，`paused` 可继续或取消，终态隐藏控制按钮。
- [x] 新增视频成品受控访问：`GET /api/v1/video-projects/{project_id}/output` 只读取数据库登记且位于 `data/` 内的 MP4。
- [x] 历史视频项返回成品 `media_url`，前端历史页支持播放视频。
- [x] 新增视频项目二次确认删除：`DELETE /api/v1/video-projects/{project_id}?confirm=true`，删除失败时返回 `partial_failed` 并保留记录。
- [x] 新增 `/api/v1/estimates/storage`，基于已登记真实图片、视频帧和输出 MP4 统计平均大小，无样本时回退经验值。
- [x] 视频任务进入终态后，前端自动刷新项目摘要、分镜版本、关键帧列表、帧问题和历史列表。
- [x] 同步 README、开发指南和 API 文档。
- [x] 运行聚焦验证：`tests/unit/test_history.py`、`tests/unit/test_video_projects.py`、`tests/integration/test_base_api.py`、Ruff、Pyright、ESLint、Prettier check 和 Node 前端测试均通过。

## 2026-06-24 视频时长输入语义调整

- [x] 将视频项目表单中的 `起始帧 / 总帧数 / 结束帧 / FPS` 改为用户可读的 `视频时长（秒） / 每秒帧数（FPS）`。
- [x] 前端自动换算 `start_frame=0`、`total_frames=round(duration_seconds * fps)`、`end_frame=total_frames - 1`，后端草稿 API 和数据库字段保持不变。
- [x] 成本、磁盘估算和草稿保存统一使用换算后的总帧数。
- [x] 同步 README、开发指南和 API 文档。

## 2026-06-24 视频分镜反馈清晰化

- [x] 将视频任务状态区增加“任务失败原因”，对 `failed` 和 `needs_attention` 显示任务 `error_message` 或错误码。
- [x] 将分镜版本区改为明确的“分镜结果”，生成或复审完成后自动加载最新版本并填入可编辑 JSON。
- [x] 分镜版本按钮显示来源和建议摘要，例如 `分镜版本 2 / AI 生成 / 加强镜头稳定性`。
- [x] 同步 README 和开发指南。

## 2026-06-24 视频透明化验收看板与参考图收纳

- [x] 视频参考图区域默认收起，按钮显示展开/收起状态和当前参考图数量；收起不清空已选文件或 media_id。
- [x] 分镜结果新增可读看板：展示整体锁定信息、关键帧表、片段运动和 AI 建议；原始 JSON 编辑能力保留。
- [x] 关键帧结果改为图片卡片，显示帧号、时间点、状态、描述、提示词、实际图片和重生成入口。
- [x] 连续帧检查显示问题帧时间点、片段范围、原因和修复入口；中间帧未完成时明确提示不会合成视频。
- [x] 后端关键帧列表和帧问题接口补充只读展示字段；Worker 对 HTTPStatusError 记录安全状态码和上游错误摘要。
- [x] Worker 对本地解析和校验异常记录脱敏后的安全摘要到任务错误和 `worker.jsonl`，便于分镜失败等问题后续排查。
- [x] 修复生产 Worker 连续帧接线：`video.frames.generate` 现在使用 `MatscaFrameGenerator.generate(...)` 的 direct 异步任务路径，支持保存和恢复 `VideoFrame.upstream_task_id`。
- [x] 连续帧 direct 异步任务遇到上游“服务重启/图片任务中断，需相同 `client_task_id` 重新提交”时，会用原任务 id 作为 `client_task_id` 自动重提并保存新的上游任务 id。
- [x] 历史页升级为视频项目历史：所有状态的视频项目都会显示，并可一键进入视频工作台继续查看、修复、重试或二次开发；进入项目只恢复界面，不自动重跑任务。
- [x] 同步 README、开发指南和 API 文档。

## 2026-06-27 Matsca 图片取回与恢复修复

- [x] 统一 Matsca 图片结果解析：同步文生图、同步图生图和异步任务结果均同时支持 `b64_json` 与 `url`；缺少图片字段或 base64 非法时返回明确错误。
- [x] 强化 URL 下载：支持 `http/https` 和 `data:image/...;base64,...`，校验 URL、HTTP 状态码、`Content-Type`、空响应、大小限制、超时和网络异常，并保留 native 下载代理。
- [x] 普通图片任务在提交前写入稳定 `client_task_id`，异步 direct 写入 `matsca_task_id`，URL 结果先写入 `result_urls` 再下载；已有 `result_urls` 时继续只重新下载。
- [x] 普通图片下载/保存失败进入 `needs_attention`，并保留 `client_task_id`、`matsca_task_id` 和 `result_urls`，不混同为上游生成失败。
- [x] 新增安全图片保存 helper：先写临时文件，检查非空，普通图片用 Pillow 校验可打开，成功后原子替换正式文件，再生成缩略图和登记媒体。
- [x] 视频关键帧、关键帧重生成、连续帧和补帧增加稳定 `client_task_id` 与 `result_url` 持久化；已有上游 task id 时继续轮询，已有 URL 时只重新下载。
- [x] 为 `VideoKeyframe` 和 `VideoFrame` 增加可空 `client_task_id`、`result_url`，并新增 Alembic migration。
- [x] 图片相关 `needs_attention` 任务可通过现有 resume 接口重新排队恢复。
- [x] 同步 README、开发指南和 API 文档。
- [x] 运行模拟验证：聚焦 pytest 121 项通过，Ruff 通过，Pyright 通过；本轮未运行真实 DeepSeek/Matsca/FFmpeg 付费 smoke。

当前固定不支持内容保持不变：Matsca 商用模式、app 模式、stream、partial images、variations、文本接口和 Responses API。

## 接口与数据变化

- `ImageJobRequest.matsca_mode` 只接受 `direct | native`；`app` 请求返回 `422`。
- 配置状态只返回 `matsca.direct` 和 `matsca.native`。
- `.env.example` 不再包含 `MATSCA_APP_*`；旧 `.env` 中同名变量由设置系统忽略。
- 图片请求支持 `moderation`、`output_compression`、`input_fidelity`。
- `VideoKeyframe` 和 `VideoFrame` 已增加可空 `upstream_task_id`、`client_task_id`、`result_url`。
- `/v1/ping` 和远程 `/v1/models` 不作为产品 API，仅保留为后续诊断能力。

## 必测场景

- Matsca direct/native 鉴权、Base URL 规范化、异步 Base64、同步 URL、上游 task id 恢复和原生下载代理边界。
- 最多 8 张参考图和动态筛选。
- 多项目共享全局并发；429、5xx、连接错误和超时。
- Worker 崩溃、lease 过期、暂停、继续、取消和重启恢复。
- 两个人工门禁、分镜版本、AI 建议、关键帧重生成和相邻片段失效。
- 缺帧补生成、超过 999 帧、FFmpeg 成功/失败。
- 媒体路径穿越、删除部分失败、旧数据库重复迁移和媒体缺失。
- 秘密扫描阻止敏感内容进入 Git。

## 第一版明确不做

- Matsca 商用模式、app 模式、stream、partial_images、variations、文本接口和 Responses API。
- AI 自动识别参考图。
- 音频、配音、音乐或音效。
- 真正的视频生成模型。
- Linux/macOS、多用户或远程访问。
- 旧 API 兼容、GitHub Actions、React/Vue。
- 无限重试或同一片段内并行中间帧。

## 执行约束

- 不得复制或提交旧凭证。
- 不得在安全扫描通过前推送。
- 不得无审批修改本计划目标、范围、步骤、优先级、验证方法、风险或下一步。
- 每完成一个既有步骤立即更新其状态。
- 每阶段运行相关验证；失败必须记录并停止错误扩散。
