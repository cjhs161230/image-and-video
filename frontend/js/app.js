export async function apiRequest(path, options = {}, fetchImpl = fetch) {
  const response = await fetchImpl(path, {
    ...options,
    headers: {
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

export function buildImageJobPayload(values) {
  return {
    model: values.model,
    prompt: values.prompt.trim(),
    n: Number(values.n),
    output_format: values.output_format,
    matsca_mode: values.matsca_mode,
  };
}

function initializeApp() {
  const app = document.querySelector("#app");
  const form = document.querySelector("#image-job-form");
  const panel = document.querySelector("#job-panel");
  const status = document.querySelector("#job-status");
  const error = document.querySelector("#job-error");
  const results = document.querySelector("#job-results");
  let activeJobId = "";
  let pollTimer;

  app.dataset.ready = "true";

  const renderJob = (job) => {
    status.textContent = job.status;
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
    if (["completed", "failed", "cancelled", "needs_attention"].includes(job.status)) {
      clearInterval(pollTimer);
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
      const created = await apiRequest("/api/v1/image-jobs", {
        method: "POST",
        body: JSON.stringify(buildImageJobPayload(values)),
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
}

if (typeof document !== "undefined") {
  initializeApp();
}
