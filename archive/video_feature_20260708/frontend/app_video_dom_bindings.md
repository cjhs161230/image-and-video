# 前端视频 DOM 绑定归档

默认 `frontend/index.html` 已移除视频项目导航和 `#video-projects` section。

旧视频 DOM 入口包括：

- `#video-draft-form`
- `#video-project-id`
- `#video-job-status`
- `#video-failure-reason`
- `#storyboard-versions`
- `#storyboard-board`
- `#storyboard-editor-form`
- `#storyboard-plan-editor`
- `#storyboard-suggestion`
- `#keyframe-list`
- `#frame-issues`
- `#frame-progress-summary`
- `#video-reference-inputs`
- `#toggle-video-references`
- `#video-reference-summary`
- `#reference-panel`

当前 `frontend/js/app.js` 对这些节点做空值保护。视频 DOM 不存在时，图片工作台、历史和设置仍应初始化。

