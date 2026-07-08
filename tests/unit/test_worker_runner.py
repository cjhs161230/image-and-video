from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from image_video.domain.jobs import JobStatus
from image_video.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from image_video.infrastructure.database.models import Job
from image_video.infrastructure.database.queue import JobQueue
from image_video.infrastructure.logging import JsonlLogger
from image_video.infrastructure.providers.matsca import (
    ProviderConfigurationError,
    UpstreamDirectUnavailableError,
)
from image_video.worker import main as worker_main
from image_video.worker.errors import RecoverableImageRetrievalError
from image_video.worker.runner import WorkerRunner


class RecordingHandler:
    def __init__(self, action: object | None = None):
        self.action = action
        self.jobs: list[str] = []

    def handle(self, job: Job, *, worker_id: str) -> None:
        self.jobs.append(job.id)
        if callable(self.action):
            self.action(job, worker_id)


def make_queue(tmp_path: Path) -> JobQueue:
    engine = create_database_engine(tmp_path / "worker.db")
    initialize_database(engine)
    return JobQueue(engine)


def test_worker_claims_dispatches_and_completes_job(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    job_id = queue.enqueue("image.generate", {"prompt": "cat"})
    handler = RecordingHandler()
    runner = WorkerRunner(
        queue=queue,
        handlers={"image.generate": handler},
        worker_id="worker-a",
        heartbeat_interval=0.01,
    )

    assert runner.run_once()

    assert handler.jobs == [job_id]
    assert queue.get(job_id).status == JobStatus.COMPLETED


def test_worker_marks_unknown_job_kind_failed(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    job_id = queue.enqueue("unknown", {})
    runner = WorkerRunner(queue=queue, handlers={}, worker_id="worker-a")

    assert not runner.run_once()

    job = queue.get(job_id)
    assert job.status == JobStatus.QUEUED
    assert job.error_code is None


def test_queue_claim_next_can_filter_allowed_job_kinds(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    video_job_id = queue.enqueue("video.frames.generate", {})
    image_job_id = queue.enqueue("image.generate", {})

    claimed = queue.claim_next(
        "worker-a", lease_seconds=60, allowed_kinds={"image.generate"}
    )

    assert claimed is not None
    assert claimed.id == image_job_id
    assert queue.get(image_job_id).status == JobStatus.RUNNING
    assert queue.get(video_job_id).status == JobStatus.QUEUED


def test_queue_claim_next_with_empty_allowed_kinds_claims_nothing(
    tmp_path: Path,
) -> None:
    queue = make_queue(tmp_path)
    job_id = queue.enqueue("image.generate", {})

    assert queue.claim_next("worker-a", allowed_kinds=set()) is None
    assert queue.get(job_id).status == JobStatus.QUEUED


def test_worker_marks_sent_timeout_as_needs_attention(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    job_id = queue.enqueue("image.generate", {})

    def timeout(job: Job, worker_id: str) -> None:
        queue.mark_upstream_request_sent(job.id, worker_id)
        raise httpx.ReadTimeout("uncertain")

    runner = WorkerRunner(
        queue=queue,
        handlers={"image.generate": RecordingHandler(timeout)},
        worker_id="worker-a",
    )

    assert runner.run_once()

    job = queue.get(job_id)
    assert job.status == JobStatus.NEEDS_ATTENTION
    assert job.error_code == "UPSTREAM_TIMEOUT"


def test_worker_marks_recoverable_image_retrieval_error_as_needs_attention(
    tmp_path: Path,
) -> None:
    queue = make_queue(tmp_path)
    job_id = queue.enqueue("image.generate", {})

    def download_failed(job: Job, worker_id: str) -> None:
        del job, worker_id
        raise RecoverableImageRetrievalError(
            error_code="IMAGE_DOWNLOAD_FAILED",
            error_message="图片下载失败：网络请求异常",
        )

    runner = WorkerRunner(
        queue=queue,
        handlers={"image.generate": RecordingHandler(download_failed)},
        worker_id="worker-a",
    )

    assert runner.run_once()

    job = queue.get(job_id)
    assert job.status == JobStatus.NEEDS_ATTENTION
    assert job.error_code == "IMAGE_DOWNLOAD_FAILED"


def test_worker_marks_upstream_direct_unavailable_with_specific_error_code(
    tmp_path: Path,
) -> None:
    queue = make_queue(tmp_path)
    job_id = queue.enqueue("image.generate", {})

    def direct_unavailable(job: Job, worker_id: str) -> None:
        queue.mark_upstream_request_sent(job.id, worker_id)
        raise UpstreamDirectUnavailableError("native unavailable")

    runner = WorkerRunner(
        queue=queue,
        handlers={"image.generate": RecordingHandler(direct_unavailable)},
        worker_id="worker-a",
    )

    assert runner.run_once()

    job = queue.get(job_id)
    assert job.status == JobStatus.FAILED
    assert job.error_code == "upstream_direct_unavailable"


def test_worker_marks_provider_configuration_error_with_specific_code(
    tmp_path: Path,
) -> None:
    queue = make_queue(tmp_path)
    job_id = queue.enqueue("image.generate", {})

    def invalid_provider_config(job: Job, worker_id: str) -> None:
        del job, worker_id
        raise ProviderConfigurationError("API Base URL 配置无效：必须是 http/https 地址")

    runner = WorkerRunner(
        queue=queue,
        handlers={"image.generate": RecordingHandler(invalid_provider_config)},
        worker_id="worker-a",
    )

    assert runner.run_once()

    job = queue.get(job_id)
    assert job.status == JobStatus.FAILED
    assert job.error_code == "PROVIDER_CONFIGURATION_ERROR"
    assert job.error_message == "供应商配置错误：API Base URL 配置无效：必须是 http/https 地址"


def test_worker_records_safe_http_status_error_details(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    job_id = queue.enqueue("video.frames.generate", {})

    def http_status_error(job: Job, worker_id: str) -> None:
        del job, worker_id
        request = httpx.Request(
            "POST",
            "https://api.example.test/api/image-tasks/edits?token=secret-token",
        )
        response = httpx.Response(
            400,
            request=request,
            json={"error": {"message": "bad image"}},
        )
        raise httpx.HTTPStatusError("bad request", request=request, response=response)

    runner = WorkerRunner(
        queue=queue,
        handlers={"video.frames.generate": RecordingHandler(http_status_error)},
        worker_id="worker-a",
    )

    assert runner.run_once()

    job = queue.get(job_id)
    assert job.status == JobStatus.FAILED
    assert job.error_code == "HTTPSTATUSERROR"
    assert job.error_message == "上游 HTTP 400：bad image"
    assert "secret-token" not in job.error_message


def test_worker_records_safe_generic_error_details(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    job_id = queue.enqueue("video.storyboard.generate", {})
    log_path = tmp_path / "logs" / "worker.jsonl"

    def invalid_storyboard(job: Job, worker_id: str) -> None:
        del job, worker_id
        raise ValueError("片段边界必须对应关键帧；Authorization: Bearer secret-token")

    runner = WorkerRunner(
        queue=queue,
        handlers={"video.storyboard.generate": RecordingHandler(invalid_storyboard)},
        worker_id="worker-a",
        logger=JsonlLogger(log_path),
    )

    assert runner.run_once()

    job = queue.get(job_id)
    assert job.status == JobStatus.FAILED
    assert job.error_code == "VALUEERROR"
    assert job.error_message == "任务处理失败：片段边界必须对应关键帧；Authorization: Bearer ***"
    log_text = log_path.read_text(encoding="utf-8")
    assert "secret-token" not in log_text
    records = [json.loads(line) for line in log_text.splitlines()]
    assert records[-1]["data"]["error_message"] == job.error_message


def test_worker_does_not_overwrite_pause_requested_during_execution(
    tmp_path: Path,
) -> None:
    queue = make_queue(tmp_path)
    job_id = queue.enqueue("image.generate", {})

    def pause(job: Job, worker_id: str) -> None:
        del worker_id
        queue.pause(job.id)

    runner = WorkerRunner(
        queue=queue,
        handlers={"image.generate": RecordingHandler(pause)},
        worker_id="worker-a",
    )

    assert runner.run_once()

    assert queue.get(job_id).status == JobStatus.PAUSED


def test_worker_recovers_expired_leases_before_polling(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    job_id = queue.enqueue("image.generate", {})
    claimed = queue.claim_next("dead-worker", lease_seconds=-1)
    assert claimed is not None
    handler = RecordingHandler()
    runner = WorkerRunner(
        queue=queue,
        handlers={"image.generate": handler},
        worker_id="worker-a",
    )

    recovered = runner.recover()
    assert runner.run_once()

    assert recovered == {"requeued": 1, "needs_attention": 0}
    assert handler.jobs == [job_id]
    assert queue.get(job_id).status == JobStatus.COMPLETED


def test_worker_writes_structured_job_lifecycle_events(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    job_id = queue.enqueue("image.generate", {"authorization": "Bearer secret"})
    log_path = tmp_path / "logs" / "worker.jsonl"
    runner = WorkerRunner(
        queue=queue,
        handlers={"image.generate": RecordingHandler()},
        worker_id="worker-a",
        logger=JsonlLogger(log_path),
    )

    assert runner.run_once()

    records = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [record["event"] for record in records] == [
        "job_started",
        "job_completed",
    ]
    assert all(record["request_id"] == job_id for record in records)
    assert "secret" not in log_path.read_text(encoding="utf-8")


def test_build_runner_wires_worker_log_under_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret_settings_type = worker_main.SecretSettings
    monkeypatch.setattr(
        worker_main,
        "SecretSettings",
        lambda: secret_settings_type(
            _env_file=None,
            matsca_direct_api_key="test-direct-key",
        ),
    )

    runner = worker_main.build_runner(tmp_path)

    assert runner.logger is not None
    assert runner.logger.path == tmp_path / "logs" / "worker.jsonl"
    image_handler = runner.handlers["image.generate"]
    provider = image_handler.matsca_provider("direct")
    assert provider.request_executor is not None
    assert provider.request_executor.logger is not None
    assert provider.request_executor.logger.path == tmp_path / "logs" / "provider.jsonl"
    dashscope = image_handler.dashscope_provider()
    assert dashscope.request_executor is not None
    assert dashscope.request_executor.provider == "dashscope"
    assert set(runner.handlers) == {"image.generate"}


def test_build_runner_registers_video_handlers_only_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret_settings_type = worker_main.SecretSettings
    monkeypatch.setattr(
        worker_main,
        "SecretSettings",
        lambda: secret_settings_type(
            _env_file=None,
            matsca_direct_api_key="test-direct-key",
            video_feature_enabled=True,
        ),
    )

    runner = worker_main.build_runner(tmp_path)

    assert "video.storyboard.generate" in runner.handlers
    assert "video.frames.generate" in runner.handlers
