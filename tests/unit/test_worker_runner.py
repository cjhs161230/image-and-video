from __future__ import annotations

from pathlib import Path

import httpx

from image_video.domain.jobs import JobStatus
from image_video.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from image_video.infrastructure.database.models import Job
from image_video.infrastructure.database.queue import JobQueue
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

    assert runner.run_once()

    job = queue.get(job_id)
    assert job.status == JobStatus.FAILED
    assert job.error_code == "UNSUPPORTED_JOB_KIND"


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
