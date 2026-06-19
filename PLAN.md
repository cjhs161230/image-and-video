# 图像与视频工作台重建与迁移执行计划

**状态：** Active  
**版本：** 1.0  
**基准日期：** 2026-06-19  
**目标目录：** `E:\auxiliary tool\image-and-video`  
**目标仓库：** GitHub 私有仓库 `image-and-video`

本文件是唯一有效执行计划。执行过程中只允许更新既有步骤的状态；目标、范围、步骤、优先级、验证方法、风险或下一步如需变化，必须先取得用户明确批准。

## 目标与固定决策

- 建立 Windows 专用、仅监听 `127.0.0.1` 的本地图像与视频工作台。
- 保留四个 DashScope/Wan/Qwen 模型，新增一个 GPT-Image-2 模型；`app/direct/native` 是调用模式，不是模型。
- 使用 FastAPI Web + 独立 Worker + SQLite 持久化队列。
- 使用 `src/image_video` 包结构、SQLAlchemy 2、Alembic、uv、原生 HTML/CSS/ES Modules。
- 图片和视频统一进入持久化任务系统，支持暂停、继续、取消和重启恢复。
- 视频流程在分镜和关键帧完成后分别暂停，用户确认后继续。
- 中间帧采用连续性优先：片段内顺序生成，片段间并行。
- Matsca 全局最大并发为官方上限 50%：应用 1、直连 5、原生 50；从 1 渐进升档，错误时降档。
- FPS 为 1–60，总帧数无硬上限，但必须进行积分、磁盘和分级确认。
- 用户可上传最多 8 张参考图并标注角色、场景或风格；DeepSeek 只读取文字标注。
- FFmpeg 使用 `D:\ffmpeg\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe`，输出静音 H.264/yuv420p MP4。
- API 统一为 `/api/v1`，不保留旧 API。
- 密钥只从 `.env` 读取，普通设置写入 Git 忽略的 `data/settings.json`。
- 运行数据全部位于 Git 忽略的 `data/`。
- 旧数据验证迁移完成后，将旧项目移动到 `E:\auxiliary tool\archives\wan-image-viewer`。

## 项目结构

```text
image-and-video/
├── AGENTS.md
├── PLAN.md
├── README.md
├── pyproject.toml
├── uv.lock
├── package.json
├── package-lock.json
├── .env.example
├── .gitignore
├── start.bat
├── stop.bat
├── alembic.ini
├── migrations/
├── src/image_video/
│   ├── api/
│   ├── application/
│   ├── domain/
│   ├── infrastructure/
│   ├── worker/
│   └── main.py
├── frontend/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── fixtures/
├── scripts/
│   ├── windows/
│   ├── migration/
│   └── security/
├── docs/
└── data/
```

## 核心接口与状态

接口资源包括健康检查、配置状态、模型、设置、图片任务、视频项目、参考图、分镜、关键帧、任务控制、历史和受控媒体访问。所有生成请求只创建持久化任务，由 Worker 执行。

视频状态：

```text
draft → planning → awaiting_storyboard_approval
→ generating_keyframes → awaiting_keyframe_approval
→ generating_frames → stitching → completed
```

辅助状态：`paused`、`cancelled`、`failed`、`needs_attention`。上游请求超时视为结果不确定，进入 `needs_attention`，不得自动重发。

## 执行阶段

### 阶段 0：安全阻塞项与计划落盘

- [x] 将本计划写入目标根目录并标记为 `Active`。
- [ ] 用户轮换旧项目中曾明文保存的 DashScope、Matsca 和 DeepSeek 凭证。
- [x] 不复制旧 `.env`、`config.json`、虚拟环境或缓存。
- [x] 检查 uv、Node、npm、Git、GitHub CLI 和 FFmpeg（`gh` 未安装，记录为阶段 13 前置项）。
- [x] 创建秘密扫描器并以测试驱动验证。
- [x] 当前工作区安全扫描通过；凭证轮换确认前不提交或推送。

### 阶段 1：项目骨架与版本管理

- [x] 建立规定目录结构、`pyproject.toml`、uv 锁文件和前端工具配置。
- [x] 创建完整 `.gitignore`、`.env.example` 和英文 `AGENTS.md`。
- [ ] 初始化本地 Git；在凭证轮换和扫描通过后创建首个提交。

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
- [x] 实现 Matsca generations/edits、三种模式、Base64/URL 和原生代理。
- [x] 实现 DeepSeek 规划、复审和有限重试。
- [x] 实现凭证级全局渐进并发、抖动、退避和错误分类。

### 阶段 5：普通图片任务

- [x] 支持四个旧模型和 GPT-Image-2 文生图/图生图。
- [x] 支持 1–4 张输出、最多 8 张输入和 PNG/JPEG/WebP。
- [x] 保存媒体、缩略图、元数据和统一历史。

### 阶段 6：视频项目与分镜门禁

- [x] 实现草稿自动保存和最多 8 张带文字标注的参考图。
- [x] DeepSeek 生成关键帧与片段运动计划并严格校验。
- [x] 分镜后暂停；支持表单编辑、版本记录、AI 建议和用户确认应用。

### 阶段 7：关键帧门禁

- [ ] 生成、预览和指定重生成 PNG 关键帧。
- [ ] 关键帧变更只使相邻片段失效。
- [ ] 关键帧完成后暂停，等待用户批准。

### 阶段 8：连续帧、恢复和合成

- [ ] 片段内顺序、片段间并行生成。
- [ ] 第一中间帧使用锚点加最多 7 张用户参考图；后续帧使用锚点、上一帧加最多 6 张用户参考图。
- [ ] 支持缺失/失效帧补生成和超时人工处理。
- [ ] 无缺帧后自动合成静音 H.264/yuv420p MP4。
- [ ] 帧编号支持超过 999。

### 阶段 9：统一历史与媒体安全

- [ ] 实现图片/视频统一历史、筛选、缩略图、封面和日志摘要。
- [ ] 媒体访问仅允许数据库登记且位于 `data/` 内的文件。
- [ ] 二次确认后删除记录和文件；部分失败必须可恢复。

### 阶段 10：前端

- [ ] 建立图片工作台、视频项目、历史、设置四个中文页面。
- [ ] 展示阶段和帧级统计，支持任务控制和两次人工门禁。
- [ ] 实现积分/磁盘估算和分级确认。
- [ ] 设置页只显示凭证配置状态。

### 阶段 11：旧数据迁移

- [ ] 使用 SQLite backup API 创建只读快照，不修改旧库。
- [ ] 根据每条记录的 `save_path` 和 `url_path` 定位真实媒体。
- [ ] 复制媒体并计算大小和 SHA-256；缺失媒体标记 `missing`。
- [ ] 归档旧日志但不导入旧密钥配置。
- [ ] 生成可审计、可重复运行的迁移报告。

### 阶段 12：启动、停止与文档

- [ ] `start.bat` 检查依赖、migration、FFmpeg，启动 Web/Worker并打开浏览器。
- [ ] `stop.bat` 只停止 PID 文件记录的本项目进程。
- [ ] 完成中文 README、需求、架构、开发、API 和迁移文档。

### 阶段 13：验证、GitHub 私有仓库和旧项目归档

- [ ] 通过 Ruff、Pyright、pytest、ESLint、Prettier 和 Chrome/Edge 小样 E2E。
- [ ] 显式运行低成本 DeepSeek/Matsca/FFmpeg smoke test。
- [ ] 再次秘密扫描并检查 Git 暂存内容。
- [ ] 创建并推送 GitHub 私有仓库 `image-and-video`。
- [ ] 最终启动验收后把计划标记 `Completed`。
- [ ] 验证绝对路径后将旧项目移动到统一归档目录，不删除。

## 必测场景

- Matsca 三模式鉴权、Base URL 规范化、Base64/URL、原生代理。
- 最多 8 张参考图和动态筛选。
- 多项目共享全局并发；429、5xx、连接错误和超时。
- Worker 崩溃、lease 过期、暂停、继续、取消和重启恢复。
- 两个人工门禁、分镜版本、AI 建议、关键帧重生成和相邻片段失效。
- 缺帧补生成、超过 999 帧、FFmpeg 成功/失败。
- 媒体路径穿越、删除部分失败、旧数据库重复迁移和媒体缺失。
- 秘密扫描阻止敏感内容进入 Git。

## 第一版明确不做

- Matsca 商用模式。
- AI 自动识别参考图。
- 音频、配音、音乐或音效。
- 真正的视频生成模型。
- Linux/macOS、多用户或远程访问。
- 旧 API 兼容、GitHub Actions、React/Vue。
- 无限重试或同一片段内并行中间帧。

## 执行约束

- 不得复制或提交旧凭证。
- 不得在安全扫描通过前推送。
- 不得在新项目完全验收前移动旧项目。
- 不得无审批修改本计划内容。
- 每完成一个既有步骤立即更新其状态。
- 每阶段运行相关验证；失败必须记录并停止错误扩散。
