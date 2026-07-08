# 图片生成工作台执行计划

**状态：** Active  
**版本：** 2.0  
**目标目录：** `E:\auxiliary tool\image-and-video`  
**默认定位：** 图片生成工作台  
**视频状态：** 已归档 / 默认停用 / 可恢复  
**视频归档目录：** `archive/video_feature_20260708/`

本文件是唯一有效执行计划。`PLAN.md` 与 `README.md` 只能整合、压缩、改写、增补；禁止无依据整段删除旧内容。确需删除旧流水账时，必须说明原因，并压缩进历史摘要或归档章节。

## 当前决策

- 默认 `VIDEO_FEATURE_ENABLED=false`。
- 默认不挂载完整视频 router，只挂载 archived video router。
- 默认不初始化 DeepSeek 视频规划器、Matsca 视频关键帧生成器、Matsca 连续帧生成器或 FFmpeg 视频合成链路。
- 默认 Worker 只注册 `image.generate`，不领取 `video.*` queued job。
- 默认前端不展示“视频项目”入口。
- 保留旧数据库、video SQLAlchemy model、video migration、history 兼容逻辑和旧公开设置字段。
- 不读取 `.env` / `.env.*`，不清理 `data/`，不调用真实付费 API，不执行 Git reset/clean/restore/commit/push。

## 历史开发摘要

原计划阶段 0-15 和 2026-06-24/27 的详细流水账已压缩为本摘要，原因是当前产品定位已调整为图片生成工作台，旧视频开发过程需要保留为历史事实而不再作为默认执行主线。

历史关键事实：

- 项目曾同时实现图片生成和逐帧视频生成方向。
- 图片主线已形成 FastAPI、独立 Worker、SQLite/Alembic、持久化任务队列、受控媒体保存和历史列表闭环。
- 视频方向曾实现草稿、分镜、关键帧、连续帧、补帧、合成、视频历史、成品受控访问和二次确认删除。
- 2026-06-24 真实付费 smoke 曾完成 DeepSeek 分镜和 Matsca direct 关键帧，连续帧阶段失败，未生成 MP4。
- 后续修复过 Matsca 图片取回、Worker 恢复、启动/停止脚本、URL 结果保存、native 诊断和 native 默认 b64 成功率等问题。
- 当前不执行真实付费 smoke；任何 DeepSeek / Matsca / FFmpeg 真实验收必须单独取得用户授权。

## 当前归档执行清单

- [x] 实施前只读检查：读取 `AGENTS.md`、`PLAN.md`、`README.md`、`.gitignore`、`pyproject.toml`、`package.json`、`.env.example`、相关后端/前端/测试/docs 文件。
- [x] 确认 `pyproject.toml` 的 pytest 配置为 `testpaths = ["tests"]`，archive 中 `.py.txt` 不会被默认收集。
- [x] 列出并覆盖 `src/image_video/api/video_projects.py` 当前所有 method + path。
- [x] 新增 `src/image_video/api/video_projects_archived.py`，默认返回 `410 VIDEO_FEATURE_ARCHIVED`。
- [x] 在 `SecretSettings` 新增 `video_feature_enabled: bool = False`，并同步 `.env.example`。
- [x] 修改 `src/image_video/main.py`：默认挂载 archived router；开启时才局部懒加载完整视频 router 和重型视频依赖。
- [x] 修改 Worker：`claim_next` 支持 `allowed_kinds`；默认 runner 只注册 `image.generate`，开启时才注册 `video.*` handler。
- [x] 修改前端：默认移除视频项目入口和视频 section；视频 DOM 缺失时图片工作台、历史、设置可初始化。
- [x] 修改 history：旧视频记录可读取但 `can_continue=false`，不引导继续视频流程。
- [x] 创建 `archive/video_feature_20260708/` 并写入恢复说明、manifest、旧代码/测试参考和文档摘要。
- [x] 同步 `README.md`、`docs/api.md`、`docs/guide.md`。
- [x] 运行全量验证命令并记录结果。
- [x] 根据验证结果完成本清单最终状态同步。

## 保留的兼容内容

- SQLAlchemy video model：`VideoProject`、`VideoReferenceImage`、`VideoStoryboardVersion`、`VideoKeyframe`、`VideoFrame`。
- Alembic video migration：
  - `migrations/versions/20260619_0003_video_projects.py`
  - `migrations/versions/20260619_0004_video_keyframes.py`
  - `migrations/versions/20260619_0005_video_frames.py`
  - `migrations/versions/20260622_0006_video_upstream_tasks.py`
  - `migrations/versions/20260627_0007_video_image_recovery_fields.py`
- `ffmpeg_path` 和 `cost_rates.video_per_frame` 旧设置字段。
- history / storage estimate 对旧视频记录和旧媒体登记的安全兼容。

## 第一版明确不做

- 不恢复默认视频 UI。
- 不删除旧 video 表。
- 不新增 drop-table migration。
- 不移动、删除或重写 video migration。
- 不清空 `data/`。
- 不调用真实图片、视频或其他付费 API。
- 不提交、不推送、不切分支、不 reset、不 clean、不 restore。

## 必测场景

- 默认 `POST /api/v1/video-projects` 返回 `VIDEO_FEATURE_ARCHIVED`。
- 默认视频子路径返回归档错误，不是简单 404。
- archived router 响应复用 envelope / request_id / error 工具。
- `video.*` queued job 默认不被 Worker 领取。
- `image.generate` 仍可闭环。
- Alembic migration 全链路仍通过，旧 video 表仍存在。
- history 遇到旧视频记录不崩溃，且不引导继续视频流程。
- 前端默认不展示“视频项目”入口。
- 视频 DOM 不存在时，图片工作台仍可初始化。
- archive 目录不影响默认 Ruff、pytest、pyright、前端测试。
