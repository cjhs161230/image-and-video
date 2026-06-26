export async function apiRequest(path, options = {}, fetchImpl = fetch) {
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  const response = await fetchImpl(path, {
    ...options,
    headers: isFormData
      ? { ...(options.headers || {}) }
      : {
          "Content-Type": "application/json",
          ...(options.headers || {}),
        },
  });
  const payload = await response.json();
  if (!response.ok || payload.error) {
    throw new Error(payload.error?.message || `请求失败：${response.status}`);
  }
  return payload.data;
}

const PAGE_IDS = ["image-workbench", "video-projects", "history", "settings"];
const THEME_IDS = ["theme-dark", "theme-light"];
const THEME_STORAGE_KEY = "image-video-theme";
const TERMINAL_JOB_STATUSES = ["completed", "failed", "cancelled", "needs_attention"];

export function normalizePageId(value) {
  const pageId = String(value || "").replace(/^#/, "");
  return PAGE_IDS.includes(pageId) ? pageId : "image-workbench";
}

export function normalizeTheme(value) {
  return THEME_IDS.includes(value) ? value : "theme-dark";
}

export function loadStoredTheme(storage = globalThis.localStorage) {
  try {
    return normalizeTheme(storage?.getItem(THEME_STORAGE_KEY));
  } catch {
    return "theme-dark";
  }
}

export function saveStoredTheme(theme, storage = globalThis.localStorage) {
  const normalized = normalizeTheme(theme);
  try {
    storage?.setItem(THEME_STORAGE_KEY, normalized);
  } catch {
    // Ignore storage errors so theme choice never blocks the workbench.
  }
  return normalized;
}

export function applyTheme(theme, root = document.documentElement) {
  const normalized = normalizeTheme(theme);
  root.dataset.theme = normalized;
  return normalized;
}

export function getControlActionsForStatus(status) {
  if (status === "queued" || status === "running") {
    return ["pause", "cancel"];
  }
  if (status === "paused") {
    return ["resume", "cancel"];
  }
  return [];
}

export function formatJobFailureMessage(job) {
  if (!["failed", "needs_attention"].includes(job.status)) {
    return "";
  }
  const actionNames = {
    "video.storyboard.generate": "生成分镜",
    "video.storyboard.review": "AI 复审分镜",
    "video.keyframes.generate": "生成关键帧",
    "video.keyframe.regenerate": "重生成关键帧",
    "video.frames.generate": "生成连续帧",
    "video.frame.repair": "修复帧",
    "video.stitch": "合成视频",
  };
  const action = actionNames[job.kind] || "视频任务";
  const statusText = job.status === "needs_attention" ? "需要人工处理" : "失败";
  return `${action}${statusText}：${job.error_message || job.error_code || "未返回具体原因"}`;
}

export function formatStoryboardVersionLabel(version) {
  const source = version.source === "user" ? "手动编辑" : "AI 生成";
  const suggestion = String(version.suggestion || "").trim();
  return `分镜版本 ${version.version} / ${source}${suggestion ? ` / ${suggestion}` : ""}`;
}

export function buildImageJobPayload(values, inputMediaIds = []) {
  const payload = {
    model: values.model,
    prompt: values.prompt.trim(),
    n: Number(values.n),
    size: String(values.size || "").trim(),
    quality: values.quality,
    style: values.style,
    background: values.background,
    moderation: values.moderation,
    output_format: values.output_format,
    input_fidelity: values.input_fidelity || undefined,
    matsca_mode: values.matsca_mode,
  };
  if (inputMediaIds.length > 0) {
    payload.input_media_ids = inputMediaIds;
  }
  const compression = String(values.output_compression || "").trim();
  if (compression) {
    payload.output_compression = Number(compression);
  }
  return payload;
}

export function estimateImageCost(values, settings = {}, storage = {}) {
  const count = Math.max(1, Number(values.n || 1));
  const diskPerItem = Number(settings.storage_estimate?.image_mb_per_item || 12);
  const diskMb = Number((count * diskPerItem).toFixed(2));
  const rate = Number(settings.cost_rates?.image_per_image || 1);
  return {
    credit_units: Number((count * rate).toFixed(2)),
    disk_mb: diskMb,
    confirmation: diskMb >= 1024 || count > 4 ? "high" : "standard",
    ...(storage.available_disk_mb ? { available_disk_mb: storage.available_disk_mb } : {}),
  };
}

export function calculateVideoFramePlan(values) {
  const fps = Math.min(60, Math.max(1, Number(values.fps || 24)));
  const durationSeconds = Math.max(0.1, Number(values.duration_seconds || 1));
  const frameCount = Math.max(1, Math.round(durationSeconds * fps));
  return {
    start_frame: 0,
    end_frame: frameCount - 1,
    total_frames: frameCount,
    fps,
    duration_seconds: Number((frameCount / fps).toFixed(3)),
  };
}

export function estimateVideoCost(values, settings = {}, storage = {}) {
  const plan = calculateVideoFramePlan(values);
  const frameCount = plan.total_frames;
  const diskPerFrame = Number(settings.storage_estimate?.video_frame_mb_per_item || 12);
  const diskMb = Number((frameCount * diskPerFrame).toFixed(2));
  const rate = Number(settings.cost_rates?.video_per_frame || 1);
  return {
    frame_count: frameCount,
    credit_units: Number((frameCount * rate).toFixed(2)),
    disk_mb: diskMb,
    confirmation:
      diskMb >= 1024 || frameCount > 100 || frameCount * rate >= 100 ? "high" : "standard",
    ...(storage.available_disk_mb ? { available_disk_mb: storage.available_disk_mb } : {}),
    fps: plan.fps,
  };
}

export function buildVideoDraftPayload(values, uploadedReferenceMediaIds = {}) {
  const plan = calculateVideoFramePlan(values);
  const references = [];
  for (let index = 1; index <= 8; index += 1) {
    const mediaId = String(
      uploadedReferenceMediaIds[index] || values[`reference_${index}_media_id`] || "",
    ).trim();
    if (!mediaId) continue;
    references.push({
      media_id: mediaId,
      label: values[`reference_${index}_label`] || "角色",
      note: String(values[`reference_${index}_note`] || "").trim(),
    });
  }
  return {
    title: String(values.title || "").trim(),
    description: String(values.description || "").trim(),
    start_frame: plan.start_frame,
    end_frame: plan.end_frame,
    total_frames: plan.total_frames,
    fps: plan.fps,
    reference_images: references,
  };
}

export function buildStoryboardVersionPayload(values) {
  try {
    return {
      source: "user",
      suggestion: String(values.storyboard_suggestion || "").trim(),
      plan: JSON.parse(String(values.storyboard_plan || "")),
    };
  } catch {
    throw new Error("分镜 JSON 格式不正确");
  }
}

function formatSeconds(value) {
  return `${Number(value || 0).toFixed(2)}s`;
}

export function buildReferenceToggleState(
  values = {},
  uploadedReferenceMediaIds = {},
  fileSelections = {},
  expanded = false,
) {
  const slots = new Set();
  for (let index = 1; index <= 8; index += 1) {
    if (String(values[`reference_${index}_media_id`] || "").trim()) {
      slots.add(index);
    }
    if (uploadedReferenceMediaIds[index]) {
      slots.add(index);
    }
    if (fileSelections[index]) {
      slots.add(index);
    }
  }
  return {
    expanded,
    buttonText: expanded ? "收起参考图" : "展开参考图",
    summaryText: `参考图：${slots.size}/8`,
    hidden: !expanded,
  };
}

export function buildStoryboardViewModel(version = {}, context = {}) {
  const fps = Number(context.fps || 24);
  const plan = version.plan || {};
  const sourceNames = { user: "手动编辑", ai: "AI 生成" };
  return {
    locks: [
      ["整体提示", plan.global_prompt || ""],
      ["角色锁定", plan.character_lock || ""],
      ["场景锁定", plan.scene_lock || ""],
      ["镜头锁定", plan.camera_lock || ""],
    ],
    keyframes: (plan.keyframes || []).map((keyframe) => ({
      frame: Number(keyframe.frame || 0),
      time: formatSeconds(Number(keyframe.frame || 0) / fps),
      description: keyframe.description || "",
      prompt: keyframe.prompt || "",
    })),
    segments: (plan.segments || []).map((segment) => {
      const start = Number(segment.start_frame || 0);
      const end = Number(segment.end_frame || 0);
      return {
        range: `${start}-${end}`,
        duration: formatSeconds((end - start + 1) / fps),
        motion: segment.motion || segment.prompt || "",
      };
    }),
    suggestion: version.suggestion || "",
    source: sourceNames[version.source] || "AI 生成",
  };
}

export function buildKeyframeViewModel(keyframe = {}, context = {}) {
  const fps = Number(context.fps || 24);
  const frame = Number(keyframe.frame || 0);
  const time = formatSeconds(keyframe.time_seconds ?? frame / fps);
  return {
    frame,
    time,
    status: keyframe.status || "",
    description: keyframe.description || "",
    prompt: keyframe.prompt || "",
    mediaUrl: keyframe.media_url || keyframe.url || "",
    imageAlt: `关键帧 ${frame}，时间 ${time}`,
  };
}

export function buildFrameIssueViewModel(issue = {}, context = {}) {
  const fps = Number(context.fps || 24);
  const frame = Number(issue.frame || 0);
  return {
    frame,
    time: formatSeconds(issue.time_seconds ?? frame / fps),
    status: issue.status || "",
    range: `片段 ${issue.segment_start_frame}-${issue.segment_end_frame}`,
    message: issue.error_message || issue.prompt || "未返回具体原因",
    repairText: `修复第 ${frame} 帧`,
  };
}

export function buildSettingsPayload(values) {
  const costRates = {};
  const imageRate = String(values.cost_rate_image_per_image || "").trim();
  const videoRate = String(values.cost_rate_video_per_frame || "").trim();
  if (imageRate) {
    costRates.image_per_image = Number(imageRate);
  }
  if (videoRate) {
    costRates.video_per_frame = Number(videoRate);
  }
  return {
    ffmpeg_path: String(values.ffmpeg_path || "").trim(),
    native_download_proxy: String(values.native_download_proxy || "").trim(),
    cost_rates: costRates,
  };
}

export function createVideoReferenceInputMarkup(count = 8) {
  return Array.from({ length: count }, (_unused, index) => {
    const slot = index + 1;
    return `
      <fieldset class="reference-slot">
        <legend>参考图 ${slot}</legend>
        <label>
          参考图 ${slot} 媒体 ID
          <input name="reference_${slot}_media_id" placeholder="可留空" />
        </label>
        <label>
          参考图 ${slot} 上传
          <input
            name="reference_${slot}_file"
            type="file"
            accept="image/png,image/jpeg,image/webp"
          />
        </label>
        <label>
          参考图 ${slot} 类型
          <select name="reference_${slot}_label">
            <option>角色</option>
            <option>场景</option>
            <option>风格</option>
          </select>
        </label>
        <label>
          参考图 ${slot} 备注
          <input name="reference_${slot}_note" />
        </label>
      </fieldset>
    `;
  }).join("");
}

export function uploadMediaFile(file, fetchImpl = fetch) {
  const formData = new FormData();
  formData.append("file", file);
  return apiRequest("/api/v1/media/upload", { method: "POST", body: formData }, fetchImpl);
}

export function getJob(jobId, fetchImpl = fetch) {
  return apiRequest(`/api/v1/jobs/${jobId}`, {}, fetchImpl);
}

export function controlJob(jobId, action, fetchImpl = fetch) {
  return apiRequest(`/api/v1/jobs/${jobId}/${action}`, { method: "POST" }, fetchImpl);
}

export function listHistory(kind = "", fetchImpl = fetch) {
  const suffix = kind ? `?kind=${encodeURIComponent(kind)}` : "";
  return apiRequest(`/api/v1/history${suffix}`, {}, fetchImpl);
}

export function buildVideoHistoryItemViewModel(item = {}) {
  const title = item.title || item.id || "未命名视频项目";
  const status = item.status || "";
  const latestJobParts = [];
  if (item.latest_job_status) {
    latestJobParts.push(String(item.latest_job_status));
  }
  if (item.latest_job_error) {
    latestJobParts.push(String(item.latest_job_error));
  }
  return {
    id: item.id,
    title,
    description: item.description || "",
    statusText: status ? `状态：${status}` : "状态：未知",
    latestJobText: latestJobParts.length ? `最近任务：${latestJobParts.join("；")}` : "",
    logSummary: item.log_summary || "",
    updatedAtText:
      item.updated_at || item.created_at ? `更新时间：${item.updated_at || item.created_at}` : "",
    mediaUrl: item.media_url || "",
    coverUrl: item.cover_url || item.thumbnail_url || "",
    canPlay: Boolean(item.media_url),
    canContinue: item.can_continue !== false,
  };
}

export async function restoreVideoProjectWorkspace(
  projectId,
  {
    fetchImpl = fetch,
    setActiveProjectId = () => {},
    setPage = () => {},
    setFormValues = () => {},
    refreshArtifacts = () => {},
  } = {},
) {
  setActiveProjectId(projectId);
  setPage("video-projects");
  const summary = await apiRequest(
    `/api/v1/video-projects/${encodeURIComponent(projectId)}`,
    {},
    fetchImpl,
  );
  setFormValues(summary);
  await refreshArtifacts(summary);
  return summary;
}

export function deleteMedia(mediaId, fetchImpl = fetch) {
  return apiRequest(
    `/api/v1/media/${encodeURIComponent(mediaId)}?confirm=true`,
    { method: "DELETE" },
    fetchImpl,
  );
}

export function deleteVideoProject(projectId, fetchImpl = fetch) {
  return apiRequest(
    `/api/v1/video-projects/${encodeURIComponent(projectId)}?confirm=true`,
    { method: "DELETE" },
    fetchImpl,
  );
}

export function getStorageEstimate(fetchImpl = fetch) {
  return apiRequest("/api/v1/estimates/storage", {}, fetchImpl);
}

export function reviewStoryboard(projectId, versionId, fetchImpl = fetch) {
  return apiRequest(
    `/api/v1/video-projects/${encodeURIComponent(projectId)}/storyboard/review`,
    {
      method: "POST",
      body: JSON.stringify({ version_id: versionId }),
    },
    fetchImpl,
  );
}

export function createDebouncedDraftSaver(save, delay = 800) {
  let timer;
  return (payload) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      Promise.resolve(save(payload)).catch(() => {});
    }, delay);
  };
}

function initializeApp() {
  const app = document.querySelector("#app");
  const form = document.querySelector("#image-job-form");
  const panel = document.querySelector("#job-panel");
  const status = document.querySelector("#job-status");
  const error = document.querySelector("#job-error");
  const results = document.querySelector("#job-results");
  const videoForm = document.querySelector("#video-draft-form");
  const videoProjectId = document.querySelector("#video-project-id");
  const videoJobStatus = document.querySelector("#video-job-status");
  const videoFailureReason = document.querySelector("#video-failure-reason");
  const videoError = document.querySelector("#video-error");
  const videoSummary = document.querySelector("#video-summary");
  const storyboardVersions = document.querySelector("#storyboard-versions");
  const storyboardBoard = document.querySelector("#storyboard-board");
  const storyboardEditorForm = document.querySelector("#storyboard-editor-form");
  const storyboardPlanEditor = document.querySelector("#storyboard-plan-editor");
  const storyboardSuggestion = document.querySelector("#storyboard-suggestion");
  const keyframeList = document.querySelector("#keyframe-list");
  const frameIssues = document.querySelector("#frame-issues");
  const frameProgressSummary = document.querySelector("#frame-progress-summary");
  const historyKind = document.querySelector("#history-kind");
  const historyList = document.querySelector("#history-list");
  const settingsForm = document.querySelector("#settings-form");
  const settingsStatus = document.querySelector("#settings-status");
  const themeSelect = document.querySelector("#theme-select");
  const imageCostEstimate = document.querySelector("#image-cost-estimate");
  const videoCostEstimate = document.querySelector("#video-cost-estimate");
  const videoFrameEstimate = document.querySelector("#video-frame-estimate");
  const imageUploadStatus = document.querySelector("#image-upload-status");
  const videoUploadStatus = document.querySelector("#video-upload-status");
  const videoReferenceInputs = document.querySelector("#video-reference-inputs");
  const referencePanel = document.querySelector("#reference-panel");
  const toggleVideoReferences = document.querySelector("#toggle-video-references");
  const videoReferenceSummary = document.querySelector("#video-reference-summary");
  let activeJobId = "";
  let activeVideoProjectId = "";
  let activeVideoJobId = "";
  let activeStoryboardVersionId = "";
  let uploadedVideoReferenceMediaIds = {};
  let videoReferencesExpanded = false;
  let publicSettings = { cost_rates: {} };
  let storageEstimate = {};
  let pollTimer;
  let videoPollTimer;

  const showPage = (pageId, updateHash = false) => {
    const activePageId = normalizePageId(pageId);
    document.querySelectorAll("[data-page]").forEach((page) => {
      page.hidden = page.id !== activePageId;
    });
    document.querySelectorAll("[data-nav-link]").forEach((link) => {
      const isActive = link.dataset.navLink === activePageId;
      link.classList.toggle("is-active", isActive);
      if (isActive) {
        link.setAttribute("aria-current", "page");
      } else {
        link.removeAttribute("aria-current");
      }
    });
    app.dataset.activePage = activePageId;
    if (updateHash && window.location.hash !== `#${activePageId}`) {
      history.pushState(null, "", `#${activePageId}`);
    }
  };

  const autosaveVideoDraft = createDebouncedDraftSaver(async (payload) => {
    if (!activeVideoProjectId) return;
    await apiRequest(`/api/v1/video-projects/${activeVideoProjectId}/draft`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    videoUploadStatus.textContent = "草稿已自动保存";
  }, 800);

  app.dataset.ready = "true";
  themeSelect.value = applyTheme(loadStoredTheme());
  showPage(window.location.hash);
  videoReferenceInputs.innerHTML = createVideoReferenceInputMarkup();

  const currentVideoReferenceFiles = () => {
    const selections = {};
    for (let index = 1; index <= 8; index += 1) {
      selections[index] = Boolean(videoForm.elements[`reference_${index}_file`]?.files?.[0]);
    }
    return selections;
  };

  const renderReferenceToggle = () => {
    const state = buildReferenceToggleState(
      Object.fromEntries(new FormData(videoForm).entries()),
      uploadedVideoReferenceMediaIds,
      currentVideoReferenceFiles(),
      videoReferencesExpanded,
    );
    toggleVideoReferences.textContent = state.buttonText;
    toggleVideoReferences.setAttribute("aria-expanded", String(state.expanded));
    videoReferenceSummary.textContent = state.summaryText;
    referencePanel.hidden = state.hidden;
  };
  renderReferenceToggle();

  document.querySelector("nav").addEventListener("click", (event) => {
    const link = event.target.closest("[data-nav-link]");
    if (!link) return;
    event.preventDefault();
    showPage(link.dataset.navLink, true);
  });

  window.addEventListener("hashchange", () => showPage(window.location.hash));

  themeSelect.addEventListener("change", () => {
    themeSelect.value = applyTheme(saveStoredTheme(themeSelect.value));
  });

  toggleVideoReferences.addEventListener("click", () => {
    videoReferencesExpanded = !videoReferencesExpanded;
    renderReferenceToggle();
  });

  videoReferenceInputs.addEventListener("input", renderReferenceToggle);
  videoReferenceInputs.addEventListener("change", renderReferenceToggle);

  const renderImageEstimate = () => {
    const estimate = estimateImageCost(
      Object.fromEntries(new FormData(form).entries()),
      publicSettings,
      storageEstimate,
    );
    imageCostEstimate.textContent =
      `积分估算：${estimate.credit_units}；磁盘估算：${estimate.disk_mb} MB` +
      (estimate.available_disk_mb ? `；可用磁盘：${estimate.available_disk_mb} MB` : "") +
      `；确认等级：${estimate.confirmation}`;
  };

  const renderVideoEstimate = () => {
    const values = Object.fromEntries(new FormData(videoForm).entries());
    const framePlan = calculateVideoFramePlan(values);
    const estimate = estimateVideoCost(values, publicSettings, storageEstimate);
    videoFrameEstimate.textContent =
      `预计生成帧数：${framePlan.total_frames}` +
      `；视频时长：${framePlan.duration_seconds} 秒` +
      `；结束帧：${framePlan.end_frame}`;
    videoCostEstimate.textContent =
      `积分估算：${estimate.credit_units}；磁盘估算：${estimate.disk_mb} MB` +
      (estimate.available_disk_mb ? `；可用磁盘：${estimate.available_disk_mb} MB` : "") +
      `；FPS：${estimate.fps}；确认等级：${estimate.confirmation}`;
  };

  const applyJobControls = (container, selector, statusValue) => {
    const allowed = new Set(getControlActionsForStatus(statusValue));
    container.querySelectorAll(selector).forEach((button) => {
      const action = button.dataset.action || button.dataset.videoJobAction || "";
      button.hidden = !allowed.has(action);
      button.disabled = !allowed.has(action);
    });
  };

  const requireCostConfirmation = (formElement, estimate) => {
    if (!formElement.elements.confirm_cost.checked) {
      throw new Error("请先确认成本");
    }
    if (estimate.confirmation === "high" && !formElement.elements.confirm_high_cost?.checked) {
      throw new Error("当前为高成本或高磁盘占用任务，请完成二次确认");
    }
  };

  const uploadImageInputs = async () => {
    const files = Array.from(form.elements.image_input_files.files || []);
    if (files.length === 0) {
      imageUploadStatus.textContent = "";
      return [];
    }
    if (files.length > 8) {
      throw new Error("图生图最多上传 8 张输入图");
    }
    imageUploadStatus.textContent = `正在上传 ${files.length} 张输入图...`;
    const uploaded = [];
    for (const file of files) {
      uploaded.push(await uploadMediaFile(file));
    }
    imageUploadStatus.textContent = `已上传 ${uploaded.length} 张输入图`;
    return uploaded.map((item) => item.media_id);
  };

  const uploadVideoReferenceInputs = async () => {
    const uploadedReferenceMediaIds = {};
    let uploadCount = 0;
    for (let index = 1; index <= 8; index += 1) {
      const file = videoForm.elements[`reference_${index}_file`]?.files?.[0];
      if (!file) continue;
      uploadCount += 1;
      uploadedReferenceMediaIds[index] = (await uploadMediaFile(file)).media_id;
    }
    videoUploadStatus.textContent = uploadCount ? `已上传 ${uploadCount} 张参考图` : "";
    uploadedVideoReferenceMediaIds = {
      ...uploadedVideoReferenceMediaIds,
      ...uploadedReferenceMediaIds,
    };
    renderReferenceToggle();
    return uploadedReferenceMediaIds;
  };

  const renderJob = (job) => {
    status.textContent = job.status;
    applyJobControls(panel, "[data-action]", job.status);
    error.textContent = job.error_message || "";
    results.replaceChildren(
      ...(job.media || []).map((media) => {
        const image = document.createElement("img");
        image.src = media.url;
        image.alt = "生成结果";
        image.loading = "lazy";
        return image;
      }),
    );
    if (TERMINAL_JOB_STATUSES.includes(job.status)) {
      clearInterval(pollTimer);
    }
  };

  const renderVideoJob = (job) => {
    videoJobStatus.textContent = `${job.kind} / ${job.status}`;
    const failureMessage = formatJobFailureMessage(job);
    videoFailureReason.textContent = failureMessage
      ? `任务失败原因：${failureMessage}`
      : "任务失败原因：暂无";
    applyJobControls(
      document.querySelector("#video-projects"),
      "[data-video-job-action]",
      job.status,
    );
    if (TERMINAL_JOB_STATUSES.includes(job.status)) {
      clearInterval(videoPollTimer);
    }
    return TERMINAL_JOB_STATUSES.includes(job.status);
  };

  const refreshVideoJob = async () => {
    if (!activeVideoJobId) return;
    try {
      const isTerminal = renderVideoJob(await getJob(activeVideoJobId));
      if (isTerminal) {
        await refreshVideoArtifacts();
      }
    } catch (requestError) {
      videoError.textContent = requestError.message;
      clearInterval(videoPollTimer);
    }
  };

  const trackVideoJob = async (created) => {
    activeVideoJobId = created.job_id;
    videoJobStatus.textContent = created.status;
    clearInterval(videoPollTimer);
    videoPollTimer = setInterval(refreshVideoJob, 1000);
    await refreshVideoJob();
  };

  const refreshVideoSummary = async () => {
    if (!activeVideoProjectId) return;
    videoSummary.textContent = JSON.stringify(
      await apiRequest(`/api/v1/video-projects/${activeVideoProjectId}`),
      null,
      2,
    );
  };

  const refreshVideoArtifacts = async () => {
    await Promise.allSettled([
      refreshVideoSummary(),
      loadStoryboardVersions(),
      loadKeyframes(),
      loadFrameIssues(),
      refreshHistory(),
    ]);
  };

  const fillVideoFormFromSummary = (summary) => {
    videoForm.elements.title.value = summary.title || "";
    videoForm.elements.description.value = summary.description || "";
    const fps = Number(summary.fps || 24);
    const totalFrames = Math.max(1, Number(summary.total_frames || 1));
    videoForm.elements.fps.value = fps;
    videoForm.elements.duration_seconds.value = Number((totalFrames / fps).toFixed(3));
    videoForm.elements.confirm_cost.checked = true;
    videoForm.elements.confirm_high_cost.checked = true;
    renderVideoEstimate();
  };

  const openVideoProject = async (projectId) => {
    await restoreVideoProjectWorkspace(projectId, {
      setActiveProjectId: (value) => {
        activeVideoProjectId = value;
        videoProjectId.textContent = value;
      },
      setPage: (pageId) => {
        showPage(pageId, true);
      },
      setFormValues: fillVideoFormFromSummary,
      refreshArtifacts: refreshVideoArtifacts,
    });
  };

  const loadStoryboardVersions = async () => {
    if (!activeVideoProjectId) return [];
    const versions = await apiRequest(
      `/api/v1/video-projects/${activeVideoProjectId}/storyboard/versions`,
    );
    storyboardVersions.replaceChildren(
      ...versions.map((version) => {
        const item = document.createElement("button");
        item.type = "button";
        item.dataset.versionId = version.version_id;
        item.dataset.plan = JSON.stringify(version.plan);
        item.dataset.suggestion = version.suggestion || "";
        item.dataset.source = version.source || "ai";
        item.textContent = formatStoryboardVersionLabel(version);
        if (version.version_id === activeStoryboardVersionId) {
          item.classList.add("is-active");
          item.setAttribute("aria-current", "true");
        }
        return item;
      }),
    );
    if (!versions.some((version) => version.version_id === activeStoryboardVersionId)) {
      activeStoryboardVersionId = versions.at(-1)?.version_id || "";
    }
    const activeVersion =
      versions.find((version) => version.version_id === activeStoryboardVersionId) ||
      versions.at(-1);
    if (activeVersion) {
      activeStoryboardVersionId = activeVersion.version_id;
      storyboardPlanEditor.value = JSON.stringify(activeVersion.plan, null, 2);
      storyboardSuggestion.value = activeVersion.suggestion || "";
      renderStoryboardBoard(activeVersion);
    } else {
      storyboardPlanEditor.value = "";
      storyboardSuggestion.value = "";
      storyboardVersions.textContent = "暂无分镜版本。请先点击“生成分镜”。";
      storyboardBoard.replaceChildren(
        Object.assign(document.createElement("h4"), { textContent: "分镜看板" }),
        Object.assign(document.createElement("p"), {
          className: "helper-text",
          textContent: "暂无分镜。请先点击“生成分镜”。",
        }),
      );
    }
    return versions;
  };

  function renderStoryboardBoard(version) {
    const values = Object.fromEntries(new FormData(videoForm).entries());
    const model = buildStoryboardViewModel(version, calculateVideoFramePlan(values));
    const title = document.createElement("h4");
    title.textContent = `分镜看板 / ${model.source}`;
    const suggestion = document.createElement("p");
    suggestion.className = "helper-text";
    suggestion.textContent = model.suggestion
      ? `AI 建议 / 修改说明：${model.suggestion}`
      : "AI 建议 / 修改说明：暂无";
    const locks = document.createElement("dl");
    locks.className = "storyboard-locks";
    for (const [label, value] of model.locks) {
      const term = document.createElement("dt");
      term.textContent = label;
      const detail = document.createElement("dd");
      detail.textContent = value || "未填写";
      locks.append(term, detail);
    }
    const keyframeTitle = document.createElement("h5");
    keyframeTitle.textContent = "分镜关键帧";
    const keyframeListView = document.createElement("div");
    keyframeListView.className = "review-list";
    keyframeListView.append(
      ...model.keyframes.map((keyframe) => {
        const item = document.createElement("article");
        item.className = "review-item";
        const heading = document.createElement("strong");
        heading.textContent = `第 ${keyframe.frame} 帧 / ${keyframe.time}`;
        const description = document.createElement("p");
        description.textContent = keyframe.description || "无描述";
        const prompt = document.createElement("p");
        prompt.textContent = keyframe.prompt || "无提示词";
        item.append(heading, description, prompt);
        return item;
      }),
    );
    const segmentTitle = document.createElement("h5");
    segmentTitle.textContent = "片段运动";
    const segmentListView = document.createElement("div");
    segmentListView.className = "review-list";
    segmentListView.append(
      ...model.segments.map((segment) => {
        const item = document.createElement("article");
        item.className = "review-item";
        const heading = document.createElement("strong");
        heading.textContent = `${segment.range} / ${segment.duration}`;
        const motion = document.createElement("p");
        motion.textContent = segment.motion || "无运动说明";
        item.append(heading, motion);
        return item;
      }),
    );
    storyboardBoard.replaceChildren(
      title,
      suggestion,
      locks,
      keyframeTitle,
      keyframeListView,
      segmentTitle,
      segmentListView,
    );
  }

  const loadKeyframes = async () => {
    if (!activeVideoProjectId) return;
    const values = Object.fromEntries(new FormData(videoForm).entries());
    const framePlan = calculateVideoFramePlan(values);
    const keyframes = await apiRequest(`/api/v1/video-projects/${activeVideoProjectId}/keyframes`);
    keyframeList.replaceChildren(
      ...keyframes.map((keyframe) => {
        const model = buildKeyframeViewModel(keyframe, framePlan);
        const wrapper = document.createElement("div");
        wrapper.className = "media-tile";
        const title = document.createElement("strong");
        title.textContent = `第 ${model.frame} 帧 / ${model.time} / ${model.status}`;
        const image = document.createElement("img");
        image.src =
          model.mediaUrl ||
          `/api/v1/video-projects/${activeVideoProjectId}/keyframes/${model.frame}/media`;
        image.alt = model.imageAlt;
        image.loading = "lazy";
        image.addEventListener("error", () => {
          image.replaceWith(
            Object.assign(document.createElement("p"), {
              className: "warning-text",
              textContent: "图片文件不存在或读取失败",
            }),
          );
        });
        const description = document.createElement("p");
        description.textContent = `描述：${model.description || "无"}`;
        const prompt = document.createElement("p");
        prompt.textContent = `提示词：${model.prompt || "无"}`;
        const button = document.createElement("button");
        button.type = "button";
        button.dataset.regenerateFrame = model.frame;
        button.textContent = `重生成第 ${model.frame} 帧`;
        wrapper.append(title, image, description, prompt, button);
        return wrapper;
      }),
    );
    if (keyframes.length > 0) {
      keyframeList.scrollIntoView({ block: "nearest" });
    }
  };

  storyboardVersions.addEventListener("click", (event) => {
    const versionButton = event.target.closest("[data-version-id]");
    if (!versionButton) return;
    activeStoryboardVersionId = versionButton.dataset.versionId;
    const version = {
      plan: JSON.parse(versionButton.dataset.plan),
      suggestion: versionButton.dataset.suggestion || "",
      source: versionButton.dataset.source || "ai",
    };
    storyboardPlanEditor.value = JSON.stringify(version.plan, null, 2);
    storyboardSuggestion.value = versionButton.dataset.suggestion || "";
    renderStoryboardBoard(version);
    storyboardVersions.querySelectorAll("[data-version-id]").forEach((button) => {
      const isActive = button.dataset.versionId === activeStoryboardVersionId;
      button.classList.toggle("is-active", isActive);
      if (isActive) {
        button.setAttribute("aria-current", "true");
      } else {
        button.removeAttribute("aria-current");
      }
    });
  });

  const loadFrameIssues = async () => {
    if (!activeVideoProjectId) return;
    const values = Object.fromEntries(new FormData(videoForm).entries());
    const framePlan = calculateVideoFramePlan(values);
    const issues = await apiRequest(`/api/v1/video-projects/${activeVideoProjectId}/frames/issues`);
    frameProgressSummary.textContent = issues.length
      ? `连续帧未完成：${issues.length} 个问题。中间帧未完成时，视频不会合成。`
      : "连续帧检查通过：没有待处理帧问题。";
    frameIssues.replaceChildren(
      ...issues.map((issue) => {
        const model = buildFrameIssueViewModel(issue, framePlan);
        const button = document.createElement("button");
        button.type = "button";
        button.dataset.repairFrame = model.frame;
        button.textContent = model.repairText;
        const item = document.createElement("article");
        item.className = "review-item";
        const title = document.createElement("strong");
        title.textContent = `第 ${model.frame} 帧 / ${model.time} / ${model.status}`;
        const range = document.createElement("p");
        range.textContent = model.range;
        const message = document.createElement("p");
        message.textContent = `原因：${model.message}`;
        item.append(title, range, message, button);
        return item;
      }),
    );
  };

  const runVideoAction = async (callback) => {
    videoError.textContent = "";
    try {
      await callback();
      await refreshVideoSummary();
    } catch (requestError) {
      videoError.textContent = requestError.message;
    }
  };

  const refreshJob = async () => {
    if (!activeJobId) return;
    try {
      renderJob(await apiRequest(`/api/v1/image-jobs/${activeJobId}`));
    } catch (requestError) {
      error.textContent = requestError.message;
      clearInterval(pollTimer);
    }
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.textContent = "";
    results.replaceChildren();
    const values = Object.fromEntries(new FormData(form).entries());
    try {
      requireCostConfirmation(form, estimateImageCost(values, publicSettings, storageEstimate));
      const inputMediaIds = await uploadImageInputs();
      const created = await apiRequest("/api/v1/image-jobs", {
        method: "POST",
        body: JSON.stringify(buildImageJobPayload(values, inputMediaIds)),
      });
      activeJobId = created.job_id;
      panel.hidden = false;
      status.textContent = created.status;
      clearInterval(pollTimer);
      pollTimer = setInterval(refreshJob, 1000);
      await refreshJob();
    } catch (requestError) {
      panel.hidden = false;
      error.textContent = requestError.message;
    }
  });

  form.addEventListener("input", renderImageEstimate);
  videoForm.addEventListener("input", () => {
    renderVideoEstimate();
    if (activeVideoProjectId) {
      autosaveVideoDraft(
        buildVideoDraftPayload(
          Object.fromEntries(new FormData(videoForm).entries()),
          uploadedVideoReferenceMediaIds,
        ),
      );
    }
  });

  panel.addEventListener("click", async (event) => {
    const action = event.target.dataset.action;
    if (!action || !activeJobId) return;
    try {
      renderJob(
        await apiRequest(`/api/v1/image-jobs/${activeJobId}/${action}`, {
          method: "POST",
        }),
      );
    } catch (requestError) {
      error.textContent = requestError.message;
    }
  });

  document.querySelector("#load-config-status").addEventListener("click", async () => {
    const target = document.querySelector("#config-status");
    try {
      target.textContent = JSON.stringify(await apiRequest("/api/v1/config/status"), null, 2);
    } catch (requestError) {
      target.textContent = requestError.message;
    }
  });

  videoForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await runVideoAction(async () => {
      const values = Object.fromEntries(new FormData(videoForm).entries());
      requireCostConfirmation(
        videoForm,
        estimateVideoCost(values, publicSettings, storageEstimate),
      );
      videoUploadStatus.textContent = "正在上传参考图...";
      uploadedVideoReferenceMediaIds = await uploadVideoReferenceInputs();
      const payload = buildVideoDraftPayload(values, uploadedVideoReferenceMediaIds);
      if (!activeVideoProjectId) {
        const created = await apiRequest("/api/v1/video-projects", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        activeVideoProjectId = created.project_id;
        videoProjectId.textContent = activeVideoProjectId;
      } else {
        await apiRequest(`/api/v1/video-projects/${activeVideoProjectId}/draft`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
      }
    });
  });

  document.querySelector("#generate-storyboard").addEventListener("click", () =>
    runVideoAction(async () => {
      requireCostConfirmation(
        videoForm,
        estimateVideoCost(
          Object.fromEntries(new FormData(videoForm).entries()),
          publicSettings,
          storageEstimate,
        ),
      );
      await trackVideoJob(
        await apiRequest(`/api/v1/video-projects/${activeVideoProjectId}/storyboard/generate`, {
          method: "POST",
        }),
      );
    }),
  );

  document.querySelector("#confirm-storyboard").addEventListener("click", () =>
    runVideoAction(async () => {
      const versions = await loadStoryboardVersions();
      const versionId = activeStoryboardVersionId || versions.at(-1)?.version_id;
      if (!versionId) throw new Error("没有可确认的分镜版本");
      await apiRequest(
        `/api/v1/video-projects/${activeVideoProjectId}/storyboard/versions/${versionId}/confirm`,
        { method: "POST" },
      );
    }),
  );

  document.querySelector("#review-storyboard").addEventListener("click", () =>
    runVideoAction(async () => {
      if (!activeVideoProjectId) throw new Error("请先创建视频项目");
      const versions = await loadStoryboardVersions();
      const versionId = activeStoryboardVersionId || versions.at(-1)?.version_id;
      if (!versionId) throw new Error("没有可复审的分镜版本");
      await trackVideoJob(await reviewStoryboard(activeVideoProjectId, versionId));
    }),
  );

  storyboardEditorForm.addEventListener("submit", (event) => {
    event.preventDefault();
    runVideoAction(async () => {
      if (!activeVideoProjectId) throw new Error("请先创建视频项目");
      await apiRequest(`/api/v1/video-projects/${activeVideoProjectId}/storyboard/versions`, {
        method: "POST",
        body: JSON.stringify(
          buildStoryboardVersionPayload(
            Object.fromEntries(new FormData(storyboardEditorForm).entries()),
          ),
        ),
      });
      await loadStoryboardVersions();
    });
  });

  document.querySelector("#generate-keyframes").addEventListener("click", () =>
    runVideoAction(async () => {
      requireCostConfirmation(
        videoForm,
        estimateVideoCost(
          Object.fromEntries(new FormData(videoForm).entries()),
          publicSettings,
          storageEstimate,
        ),
      );
      await trackVideoJob(
        await apiRequest(`/api/v1/video-projects/${activeVideoProjectId}/keyframes/generate`, {
          method: "POST",
        }),
      );
      await loadKeyframes();
    }),
  );

  document.querySelector("#confirm-keyframes").addEventListener("click", () =>
    runVideoAction(async () => {
      await apiRequest(`/api/v1/video-projects/${activeVideoProjectId}/keyframes/confirm`, {
        method: "POST",
      });
    }),
  );

  document.querySelector("#generate-frames").addEventListener("click", () =>
    runVideoAction(async () => {
      requireCostConfirmation(
        videoForm,
        estimateVideoCost(
          Object.fromEntries(new FormData(videoForm).entries()),
          publicSettings,
          storageEstimate,
        ),
      );
      await trackVideoJob(
        await apiRequest(`/api/v1/video-projects/${activeVideoProjectId}/frames/generate`, {
          method: "POST",
        }),
      );
    }),
  );

  document
    .querySelector("#check-frame-issues")
    .addEventListener("click", () => runVideoAction(loadFrameIssues));

  document.querySelector("#stitch-video").addEventListener("click", () =>
    runVideoAction(async () => {
      requireCostConfirmation(videoForm);
      await trackVideoJob(
        await apiRequest(`/api/v1/video-projects/${activeVideoProjectId}/stitch`, {
          method: "POST",
        }),
      );
    }),
  );

  keyframeList.addEventListener("click", async (event) => {
    const frame = event.target.dataset.regenerateFrame;
    if (!frame) return;
    await runVideoAction(async () => {
      await trackVideoJob(
        await apiRequest(
          `/api/v1/video-projects/${activeVideoProjectId}/keyframes/${frame}/regenerate`,
          { method: "POST" },
        ),
      );
      await loadKeyframes();
    });
  });

  frameIssues.addEventListener("click", async (event) => {
    const frame = event.target.dataset.repairFrame;
    if (!frame) return;
    await runVideoAction(async () => {
      await trackVideoJob(
        await apiRequest(`/api/v1/video-projects/${activeVideoProjectId}/frames/${frame}/repair`, {
          method: "POST",
        }),
      );
      await loadFrameIssues();
    });
  });

  document.querySelector("#video-projects").addEventListener("click", async (event) => {
    const action = event.target.dataset.videoJobAction;
    if (!action || !activeVideoJobId) return;
    try {
      renderVideoJob(await controlJob(activeVideoJobId, action));
    } catch (requestError) {
      videoError.textContent = requestError.message;
    }
  });

  const refreshHistory = async () => {
    const items = await listHistory(historyKind.value);
    historyList.replaceChildren(
      ...items.map((item) => {
        const row = document.createElement("article");
        row.className = "history-item";
        if (item.cover_url) {
          const image = document.createElement("img");
          image.src = item.cover_url;
          image.alt = item.kind === "video" ? "视频封面" : "图片缩略图";
          row.append(image);
        }
        const text = document.createElement("p");
        text.textContent = `${item.kind} ${item.id} ${item.log_summary || ""}`;
        row.append(text);
        if (item.kind === "image" && item.media_url) {
          const button = document.createElement("button");
          button.type = "button";
          button.dataset.deleteMediaId = item.id;
          button.textContent = "删除记录";
          row.append(button);
        }
        if (item.kind === "video") {
          const model = buildVideoHistoryItemViewModel(item);
          text.textContent = `${model.title} ${model.statusText}${
            model.latestJobText ? ` ${model.latestJobText}` : ""
          }${model.logSummary ? ` ${model.logSummary}` : ""}`;
          if (model.description) {
            const description = document.createElement("p");
            description.textContent = model.description;
            row.append(description);
          }
          if (model.updatedAtText) {
            const updatedAt = document.createElement("p");
            updatedAt.textContent = model.updatedAtText;
            row.append(updatedAt);
          }
          const openButton = document.createElement("button");
          openButton.type = "button";
          openButton.dataset.openVideoProjectId = item.id;
          openButton.textContent = "进入项目";
          row.append(openButton);
          if (item.media_url) {
            const link = document.createElement("a");
            link.href = item.media_url;
            link.target = "_blank";
            link.rel = "noreferrer";
            link.textContent = "播放视频";
            row.append(link);
          }
          const button = document.createElement("button");
          button.type = "button";
          button.dataset.deleteVideoProjectId = item.id;
          button.textContent = "删除项目";
          row.append(button);
        }
        return row;
      }),
    );
  };

  document.querySelector("#refresh-history").addEventListener("click", refreshHistory);

  historyList.addEventListener("click", async (event) => {
    const mediaId = event.target.dataset.deleteMediaId;
    const projectId = event.target.dataset.deleteVideoProjectId;
    const openProjectId = event.target.dataset.openVideoProjectId;
    if (openProjectId) {
      try {
        await openVideoProject(openProjectId);
      } catch (requestError) {
        const row = event.target.closest(".history-item");
        if (row) {
          const errorText = document.createElement("p");
          errorText.textContent = requestError.message;
          row.append(errorText);
        }
      }
      return;
    }
    if (!mediaId && !projectId) return;
    if (!globalThis.confirm("确认删除这条历史记录和媒体文件？")) return;
    try {
      if (mediaId) {
        await deleteMedia(mediaId);
      } else {
        await deleteVideoProject(projectId);
      }
      document.querySelector("#refresh-history").click();
    } catch (requestError) {
      const row = event.target.closest(".history-item");
      if (row) {
        const errorText = document.createElement("p");
        errorText.textContent = requestError.message;
        row.append(errorText);
      }
    }
  });

  settingsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      publicSettings = await apiRequest("/api/v1/settings", {
        method: "PATCH",
        body: JSON.stringify(buildSettingsPayload(Object.fromEntries(new FormData(settingsForm)))),
      });
      settingsStatus.textContent = "设置已保存";
      renderImageEstimate();
      renderVideoEstimate();
    } catch (requestError) {
      settingsStatus.textContent = requestError.message;
    }
  });

  apiRequest("/api/v1/settings")
    .then((settings) => {
      publicSettings = settings;
      settingsForm.elements.ffmpeg_path.value = settings.ffmpeg_path || "";
      settingsForm.elements.native_download_proxy.value = settings.native_download_proxy || "";
      settingsForm.elements.cost_rate_image_per_image.value =
        settings.cost_rates?.image_per_image ?? "";
      settingsForm.elements.cost_rate_video_per_frame.value =
        settings.cost_rates?.video_per_frame ?? "";
      renderImageEstimate();
      renderVideoEstimate();
    })
    .catch(() => {
      renderImageEstimate();
      renderVideoEstimate();
    });
  getStorageEstimate()
    .then((estimate) => {
      publicSettings = { ...publicSettings, storage_estimate: estimate };
      renderImageEstimate();
      renderVideoEstimate();
    })
    .catch(() => {});
  if (navigator?.storage?.estimate) {
    navigator.storage
      .estimate()
      .then((info) => {
        storageEstimate = {
          available_disk_mb:
            info.quota && info.usage
              ? Math.max(0, Math.round((info.quota - info.usage) / 1024 / 1024))
              : 0,
        };
        renderImageEstimate();
        renderVideoEstimate();
      })
      .catch(() => {});
  }
}

if (typeof document !== "undefined") {
  initializeApp();
}
