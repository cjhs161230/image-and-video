"""Persistent queue worker loop."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Protocol

import httpx

from image_video.infrastructure.database.models import Job
from image_video.infrastructure.database.queue import JobQueue


class JobHandler(Protocol):
    def handle(self, job: Job, *, worker_id: str) -> None: ...


class WorkerRunner:
    def __init__(
        self,
        *,
        queue: JobQueue,
        handlers: Mapping[str, JobHandler],
        worker_id: str,
        lease_seconds: int = 60,
        heartbeat_interval: float = 20,
        poll_interval: float = 1,
    ):
        self.queue = queue
        self.handlers = handlers
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.heartbeat_interval = heartbeat_interval
        self.poll_interval = poll_interval
        self.stop_event = threading.Event()

    def recover(self) -> dict[str, int]:
        return self.queue.recover_expired()

    def run_once(self) -> bool:
        job = self.queue.claim_next(self.worker_id, lease_seconds=self.lease_seconds)
        if job is None:
            return False
        handler = self.handlers.get(job.kind)
        if handler is None:
            self._try_fail(
                job.id,
                error_code="UNSUPPORTED_JOB_KIND",
                error_message="不支持的任务类型",
            )
            return True

        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat_loop,
            args=(job.id, heartbeat_stop),
            daemon=True,
        )
        heartbeat.start()
        try:
            handler.handle(job, worker_id=self.worker_id)
            self._try_complete(job.id)
        except httpx.TimeoutException:
            self._try_needs_attention(
                job.id,
                error_code="UPSTREAM_TIMEOUT",
                error_message="上游请求超时，结果状态不确定",
            )
        except Exception as exc:
            self._try_fail(
                job.id,
                error_code=type(exc).__name__.upper(),
                error_message="任务处理失败",
            )
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=max(1, self.heartbeat_interval * 2))
        return True

    def run_forever(self) -> None:
        self.recover()
        while not self.stop_event.is_set():
            if not self.run_once():
                self.stop_event.wait(self.poll_interval)

    def stop(self) -> None:
        self.stop_event.set()

    def _heartbeat_loop(self, job_id: str, stop: threading.Event) -> None:
        while not stop.wait(self.heartbeat_interval):
            if not self.queue.heartbeat(
                job_id, self.worker_id, lease_seconds=self.lease_seconds
            ):
                return

    def _try_complete(self, job_id: str) -> None:
        try:
            self.queue.complete(job_id, self.worker_id)
        except KeyError:
            return

    def _try_fail(self, job_id: str, *, error_code: str, error_message: str) -> None:
        try:
            self.queue.fail(
                job_id,
                self.worker_id,
                error_code=error_code,
                error_message=error_message,
            )
        except KeyError:
            return

    def _try_needs_attention(
        self, job_id: str, *, error_code: str, error_message: str
    ) -> None:
        try:
            self.queue.needs_attention(
                job_id,
                self.worker_id,
                error_code=error_code,
                error_message=error_message,
            )
        except KeyError:
            return
