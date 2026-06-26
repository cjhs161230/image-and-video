import assert from "node:assert/strict";

import {
  apiRequest,
  buildImageJobPayload,
  buildStoryboardVersionPayload,
  buildSettingsPayload,
  buildVideoDraftPayload,
  calculateVideoFramePlan,
  estimateImageCost,
  estimateVideoCost,
  formatJobFailureMessage,
  formatStoryboardVersionLabel,
  getControlActionsForStatus,
  controlJob,
  createDebouncedDraftSaver,
  deleteMedia,
  deleteVideoProject,
  listHistory,
  getStorageEstimate,
  loadStoredTheme,
  normalizePageId,
  normalizeTheme,
  buildFrameIssueViewModel,
  buildKeyframeViewModel,
  buildReferenceToggleState,
  buildStoryboardViewModel,
  buildVideoHistoryItemViewModel,
  restoreVideoProjectWorkspace,
  reviewStoryboard,
  saveStoredTheme,
} from "../../frontend/js/app.js";

const payload = buildImageJobPayload(
  {
    model: "gpt-image-2",
    prompt: "一只猫",
    n: "2",
    size: "1536x1024",
    quality: "high",
    style: "natural",
    background: "transparent",
    moderation: "low",
    output_format: "png",
    output_compression: "",
    input_fidelity: "high",
    matsca_mode: "direct",
  },
  ["media-1", "media-2"],
);

assert.deepEqual(payload, {
  model: "gpt-image-2",
  prompt: "一只猫",
  n: 2,
  size: "1536x1024",
  quality: "high",
  style: "natural",
  background: "transparent",
  moderation: "low",
  output_format: "png",
  input_fidelity: "high",
  matsca_mode: "direct",
  input_media_ids: ["media-1", "media-2"],
});

assert.equal(normalizePageId("#image-workbench"), "image-workbench");
assert.equal(normalizePageId("video-projects"), "video-projects");
assert.equal(normalizePageId("#missing"), "image-workbench");
assert.equal(normalizePageId(""), "image-workbench");

assert.equal(normalizeTheme("theme-light"), "theme-light");
assert.equal(normalizeTheme("unknown"), "theme-dark");
assert.equal(normalizeTheme(null), "theme-dark");

const memoryStorage = new Map();
const storage = {
  getItem: (key) => memoryStorage.get(key) ?? null,
  setItem: (key, value) => memoryStorage.set(key, value),
};
assert.equal(loadStoredTheme(storage), "theme-dark");
saveStoredTheme("theme-light", storage);
assert.equal(loadStoredTheme(storage), "theme-light");
saveStoredTheme("broken", storage);
assert.equal(loadStoredTheme(storage), "theme-dark");

assert.deepEqual(estimateImageCost({ n: 3 }), {
  credit_units: 3,
  disk_mb: 36,
  confirmation: "standard",
});

assert.deepEqual(
  estimateImageCost(
    { n: 3 },
    { cost_rates: { image_per_image: 1 }, storage_estimate: { image_mb_per_item: 2 } },
  ),
  {
    credit_units: 3,
    disk_mb: 6,
    confirmation: "standard",
  },
);

assert.deepEqual(
  estimateImageCost(
    { n: 3 },
    { cost_rates: { image_per_image: 2.5 } },
    { available_disk_mb: 2048 },
  ),
  {
    credit_units: 7.5,
    disk_mb: 36,
    confirmation: "standard",
    available_disk_mb: 2048,
  },
);

assert.deepEqual(calculateVideoFramePlan({ duration_seconds: "2.5", fps: "24" }), {
  start_frame: 0,
  end_frame: 59,
  total_frames: 60,
  fps: 24,
  duration_seconds: 2.5,
});

assert.deepEqual(
  estimateVideoCost({
    duration_seconds: "5",
    fps: "24",
  }),
  {
    frame_count: 120,
    credit_units: 120,
    disk_mb: 1440,
    confirmation: "high",
    fps: 24,
  },
);

assert.deepEqual(
  estimateVideoCost(
    {
      duration_seconds: "2",
      fps: "24",
    },
    {
      cost_rates: { video_per_frame: 1.5 },
      storage_estimate: { video_frame_mb_per_item: 2 },
    },
    { available_disk_mb: 4096 },
  ),
  {
    frame_count: 48,
    credit_units: 72,
    disk_mb: 96,
    confirmation: "standard",
    available_disk_mb: 4096,
    fps: 24,
  },
);

assert.deepEqual(getControlActionsForStatus("queued"), ["pause", "cancel"]);
assert.deepEqual(getControlActionsForStatus("running"), ["pause", "cancel"]);
assert.deepEqual(getControlActionsForStatus("paused"), ["resume", "cancel"]);
assert.deepEqual(getControlActionsForStatus("completed"), []);
assert.deepEqual(getControlActionsForStatus("failed"), []);
assert.deepEqual(getControlActionsForStatus("cancelled"), []);
assert.deepEqual(getControlActionsForStatus("needs_attention"), []);

assert.equal(
  formatJobFailureMessage({
    kind: "video.storyboard.review",
    status: "failed",
    error_code: "upstream_error",
    error_message: "DeepSeek 返回内容不是合法 JSON",
  }),
  "AI 复审分镜失败：DeepSeek 返回内容不是合法 JSON",
);
assert.equal(
  formatJobFailureMessage({
    kind: "video.storyboard.generate",
    status: "needs_attention",
    error_message: "上游请求超时，结果状态不确定",
  }),
  "生成分镜需要人工处理：上游请求超时，结果状态不确定",
);
assert.equal(formatJobFailureMessage({ kind: "video.stitch", status: "completed" }), "");

assert.equal(
  formatStoryboardVersionLabel({
    version: 2,
    source: "ai",
    suggestion: "加强镜头稳定性",
  }),
  "分镜版本 2 / AI 生成 / 加强镜头稳定性",
);
assert.equal(
  formatStoryboardVersionLabel({
    version: 3,
    source: "user",
    suggestion: "",
  }),
  "分镜版本 3 / 手动编辑",
);

assert.deepEqual(
  buildVideoDraftPayload(
    {
      title: "演示",
      description: "角色转身",
      duration_seconds: "2.5",
      fps: "24",
      reference_1_media_id: "media-1",
      reference_1_label: "角色",
      reference_1_note: "主角",
      reference_2_media_id: "",
      reference_2_label: "场景",
      reference_2_note: "",
    },
    { 2: "uploaded-media-2" },
  ),
  {
    title: "演示",
    description: "角色转身",
    start_frame: 0,
    end_frame: 59,
    total_frames: 60,
    fps: 24,
    reference_images: [
      { media_id: "media-1", label: "角色", note: "主角" },
      { media_id: "uploaded-media-2", label: "场景", note: "" },
    ],
  },
);

assert.deepEqual(
  buildReferenceToggleState(
    {
      reference_1_media_id: "media-1",
      reference_2_media_id: "",
      reference_3_media_id: "media-3",
    },
    { 2: "uploaded-media-2" },
    { 4: true },
    false,
  ),
  {
    expanded: false,
    buttonText: "展开参考图",
    summaryText: "参考图：4/8",
    hidden: true,
  },
);
assert.deepEqual(buildReferenceToggleState({}, {}, {}, true), {
  expanded: true,
  buttonText: "收起参考图",
  summaryText: "参考图：0/8",
  hidden: false,
});

assert.deepEqual(
  buildStoryboardViewModel({
    plan: {
      global_prompt: "整体风格",
      character_lock: "主角一致",
      scene_lock: "街道",
      camera_lock: "固定镜头",
      keyframes: [
        { frame: 0, description: "开场", prompt: "start" },
        { frame: 9, description: "结束", prompt: "end" },
      ],
      segments: [{ start_frame: 0, end_frame: 9, motion: "慢慢转身" }],
    },
    source: "ai",
    suggestion: "加强稳定性",
  }),
  {
    locks: [
      ["整体提示", "整体风格"],
      ["角色锁定", "主角一致"],
      ["场景锁定", "街道"],
      ["镜头锁定", "固定镜头"],
    ],
    keyframes: [
      { frame: 0, time: "0.00s", description: "开场", prompt: "start" },
      { frame: 9, time: "0.38s", description: "结束", prompt: "end" },
    ],
    segments: [{ range: "0-9", duration: "0.42s", motion: "慢慢转身" }],
    suggestion: "加强稳定性",
    source: "AI 生成",
  },
);

assert.deepEqual(
  buildKeyframeViewModel(
    {
      frame: 9,
      status: "completed",
      description: "结束",
      prompt: "end prompt",
      media_url: "/api/v1/video-projects/project/keyframes/9/media",
    },
    { fps: 10 },
  ),
  {
    frame: 9,
    time: "0.90s",
    status: "completed",
    description: "结束",
    prompt: "end prompt",
    mediaUrl: "/api/v1/video-projects/project/keyframes/9/media",
    imageAlt: "关键帧 9，时间 0.90s",
  },
);

assert.deepEqual(
  buildFrameIssueViewModel(
    {
      frame: 3,
      status: "failed",
      error_message: "Matsca HTTP 400",
      segment_start_frame: 0,
      segment_end_frame: 9,
    },
    { fps: 10 },
  ),
  {
    frame: 3,
    time: "0.30s",
    status: "failed",
    range: "片段 0-9",
    message: "Matsca HTTP 400",
    repairText: "修复第 3 帧",
  },
);

assert.deepEqual(
  buildStoryboardVersionPayload({
    storyboard_plan:
      '{"global_prompt":"scene","character_lock":"hero","scene_lock":"street","camera_lock":"wide","keyframes":[{"frame":0,"description":"start","prompt":"start"}],"segments":[]}',
    storyboard_suggestion: "加强镜头稳定性",
  }),
  {
    source: "user",
    suggestion: "加强镜头稳定性",
    plan: {
      global_prompt: "scene",
      character_lock: "hero",
      scene_lock: "street",
      camera_lock: "wide",
      keyframes: [{ frame: 0, description: "start", prompt: "start" }],
      segments: [],
    },
  },
);

assert.throws(
  () => buildStoryboardVersionPayload({ storyboard_plan: "{broken" }),
  /分镜 JSON 格式不正确/,
);

assert.deepEqual(
  buildSettingsPayload({
    ffmpeg_path: "D:/ffmpeg/bin/ffmpeg.exe",
    native_download_proxy: "http://127.0.0.1:7890",
    cost_rate_image_per_image: "2.5",
    cost_rate_video_per_frame: "1.5",
    api_key: "must-not-send",
  }),
  {
    ffmpeg_path: "D:/ffmpeg/bin/ffmpeg.exe",
    native_download_proxy: "http://127.0.0.1:7890",
    cost_rates: {
      image_per_image: 2.5,
      video_per_frame: 1.5,
    },
  },
);

const calls = [];
const data = await apiRequest(
  "/api/v1/image-jobs",
  { method: "POST", body: JSON.stringify(payload) },
  async (url, options) => {
    calls.push([url, options]);
    return new Response(
      JSON.stringify({
        data: { job_id: "job-1", status: "queued" },
        error: null,
        request_id: "request-1",
      }),
      { status: 202, headers: { "Content-Type": "application/json" } },
    );
  },
);

assert.equal(data.job_id, "job-1");
assert.equal(calls[0][0], "/api/v1/image-jobs");
assert.equal(calls[0][1].headers["Content-Type"], "application/json");

await assert.rejects(
  () =>
    apiRequest("/api/v1/image-jobs/missing", {}, async () => {
      return new Response(
        JSON.stringify({
          data: null,
          error: { code: "NOT_FOUND", message: "资源不存在" },
          request_id: "request-2",
        }),
        { status: 404, headers: { "Content-Type": "application/json" } },
      );
    }),
  /资源不存在/,
);

const historyCalls = [];
const history = await listHistory("video", async (url, options) => {
  historyCalls.push([url, options]);
  return new Response(
    JSON.stringify({
      data: [{ id: "project-1", kind: "video", cover_url: "/cover.png" }],
      error: null,
      request_id: "request-3",
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
});

assert.equal(historyCalls[0][0], "/api/v1/history?kind=video");
assert.equal(history[0].id, "project-1");

const incompleteVideoHistory = buildVideoHistoryItemViewModel({
  id: "project-draft",
  title: "草稿视频",
  description: "继续生成",
  status: "failed",
  latest_job_status: "failed",
  latest_job_error: "上游 HTTP 502",
  media_url: "",
  updated_at: "2026-06-24T10:00:00Z",
});
assert.equal(incompleteVideoHistory.title, "草稿视频");
assert.equal(incompleteVideoHistory.statusText, "状态：failed");
assert.equal(incompleteVideoHistory.latestJobText, "最近任务：failed；上游 HTTP 502");
assert.equal(incompleteVideoHistory.canPlay, false);
assert.equal(incompleteVideoHistory.canContinue, true);

const completedVideoHistory = buildVideoHistoryItemViewModel({
  id: "project-done",
  kind: "video",
  status: "completed",
  media_url: "/api/v1/video-projects/project-done/output",
});
assert.equal(completedVideoHistory.canPlay, true);

const restoreCalls = [];
const restoredProject = await restoreVideoProjectWorkspace("project-restore", {
  fetchImpl: async (url) => {
    restoreCalls.push(url);
    if (url === "/api/v1/video-projects/project-restore") {
      return new Response(
        JSON.stringify({
          data: {
            project_id: "project-restore",
            title: "恢复项目",
            description: "继续做",
            total_frames: 10,
            fps: 10,
            status: "awaiting_keyframe_approval",
          },
          error: null,
          request_id: "restore-summary",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    return new Response(JSON.stringify({ data: [], error: null, request_id: "restore-empty" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  },
  setActiveProjectId: (projectId) => restoreCalls.push(`active:${projectId}`),
  setPage: (pageId) => restoreCalls.push(`page:${pageId}`),
  setFormValues: (summary) => restoreCalls.push(`form:${summary.title}:${summary.fps}`),
  refreshArtifacts: () => restoreCalls.push("artifacts"),
});
assert.equal(restoredProject.project_id, "project-restore");
assert.deepEqual(restoreCalls, [
  "active:project-restore",
  "page:video-projects",
  "/api/v1/video-projects/project-restore",
  "form:恢复项目:10",
  "artifacts",
]);

const jobCalls = [];
await controlJob("job-1", "pause", async (url, options) => {
  jobCalls.push([url, options]);
  return new Response(
    JSON.stringify({
      data: { id: "job-1", status: "paused" },
      error: null,
      request_id: "request-4",
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
});

assert.equal(jobCalls[0][0], "/api/v1/jobs/job-1/pause");
assert.equal(jobCalls[0][1].method, "POST");

const deleteCalls = [];
await deleteMedia("media-1", async (url, options) => {
  deleteCalls.push([url, options]);
  return new Response(
    JSON.stringify({
      data: { id: "media-1", status: "deleted" },
      error: null,
      request_id: "request-5",
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
});

assert.equal(deleteCalls[0][0], "/api/v1/media/media-1?confirm=true");
assert.equal(deleteCalls[0][1].method, "DELETE");

const deleteVideoCalls = [];
await deleteVideoProject("project-1", async (url, options) => {
  deleteVideoCalls.push([url, options]);
  return new Response(
    JSON.stringify({
      data: { id: "project-1", status: "deleted" },
      error: null,
      request_id: "request-video-delete",
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
});

assert.equal(deleteVideoCalls[0][0], "/api/v1/video-projects/project-1?confirm=true");
assert.equal(deleteVideoCalls[0][1].method, "DELETE");

const estimateCalls = [];
const storageEstimate = await getStorageEstimate(async (url, options) => {
  estimateCalls.push([url, options]);
  return new Response(
    JSON.stringify({
      data: {
        source: "real",
        image_mb_per_item: 2,
        video_frame_mb_per_item: 3,
        video_output_mb_per_project: 4,
      },
      error: null,
      request_id: "request-estimate",
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
});

assert.equal(estimateCalls[0][0], "/api/v1/estimates/storage");
assert.equal(storageEstimate.video_frame_mb_per_item, 3);

const reviewCalls = [];
await reviewStoryboard("project-1", "version-1", async (url, options) => {
  reviewCalls.push([url, options]);
  return new Response(
    JSON.stringify({
      data: {
        project_id: "project-1",
        version_id: "version-1",
        job_id: "review-job-1",
        status: "queued",
      },
      error: null,
      request_id: "request-6",
    }),
    { status: 202, headers: { "Content-Type": "application/json" } },
  );
});

assert.equal(reviewCalls[0][0], "/api/v1/video-projects/project-1/storyboard/review");
assert.equal(reviewCalls[0][1].method, "POST");
assert.deepEqual(JSON.parse(reviewCalls[0][1].body), {
  version_id: "version-1",
});

const savedDrafts = [];
const saveDraft = createDebouncedDraftSaver(async (payload) => savedDrafts.push(payload), 10);
saveDraft({ title: "first" });
saveDraft({ title: "latest" });
await new Promise((resolve) => setTimeout(resolve, 30));
assert.deepEqual(savedDrafts, [{ title: "latest" }]);
