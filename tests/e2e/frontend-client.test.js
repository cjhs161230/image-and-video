import assert from "node:assert/strict";

import { apiRequest, buildImageJobPayload } from "../../frontend/js/app.js";

const payload = buildImageJobPayload({
  model: "gpt-image-2",
  prompt: "一只猫",
  n: "2",
  output_format: "png",
  matsca_mode: "direct",
});

assert.deepEqual(payload, {
  model: "gpt-image-2",
  prompt: "一只猫",
  n: 2,
  output_format: "png",
  matsca_mode: "direct",
});

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
