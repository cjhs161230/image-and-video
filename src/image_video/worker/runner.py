"""Persistent queue worker loop."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any, Protocol, cast

import httpx

from image_video.infrastructure.database.models import Job
from image_video.infrastructure.database.queue import JobQueue
from image_video.infrastructure.logging import JsonlLogger, redact_sensitive
from image_video.infrastructure.providers.matsca import UpstreamDirectUnavailableError
from image_video.worker.errors import RecoverableImageRetrievalError


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
        logger: JsonlLogger | None = None,
    ):
        self.queue = queue
        self.handlers = handlers
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.heartbeat_interval = heartbeat_interval
        self.poll_interval = poll_interval
        self.logger = logger
        self.stop_event = threading.Event()

    def recover(self) -> dict[str, int]:
        return self.queue.recover_expired()

    def run_once(self) -> bool:
        job = self.queue.claim_next(self.worker_id, lease_seconds=self.lease_seconds)
        if job is None:
            return False
        self._log(
            level="info",
            event="job_started",
            job_id=job.id,
            data={"job_kind": job.kind, "attempt_count": job.attempt_count},
        )
        handler = self.handlers.get(job.kind)
        if handler is None:
            self._try_fail(
                job.id,
                error_code="UNSUPPORTED_JOB_KIND",
                error_message="不支持的任务类型",
            )
            self._log(
                level="error",
                event="job_failed",
                job_id=job.id,
                data={"job_kind": job.kind, "error_code": "UNSUPPORTED_JOB_KIND"},
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
            self._log(
                level="info",
                event="job_completed",
                job_id=job.id,
                data={"job_kind": job.kind},
            )
        except httpx.TimeoutException:
            self._try_needs_attention(
                job.id,
                error_code="UPSTREAM_TIMEOUT",
                error_message="上游请求超时，结果状态不确定",
            )
            self._log(
                level="warning",
                event="job_needs_attention",
                job_id=job.id,
                data={"job_kind": job.kind, "error_code": "UPSTREAM_TIMEOUT"},
            )
        except RecoverableImageRetrievalError as exc:
            self._try_needs_attention(
                job.id,
                error_code=exc.error_code,
                error_message=exc.error_message,
            )
            self._log(
                level="warning",
                event="job_needs_attention",
                job_id=job.id,
                data={"job_kind": job.kind, "error_code": exc.error_code},
            )
        except UpstreamDirectUnavailableError as exc:
            self._try_fail(
                job.id,
                error_code="upstream_direct_unavailable",
                error_message=str(exc),
            )
            self._log(
                level="error",
                event="job_failed",
                job_id=job.id,
                data={
                    "job_kind": job.kind,
                    "error_code": "upstream_direct_unavailable",
                },
            )
        except httpx.HTTPStatusError as exc:
            self._try_fail(
                job.id,
                error_code="HTTPSTATUSERROR",
                error_message=_safe_http_status_error_message(exc),
            )
            self._log(
                level="error",
                event="job_failed",
                job_id=job.id,
                data={"job_kind": job.kind, "error_code": "HTTPSTATUSERROR"},
            )
        except Exception as exc:
            error_message = _safe_exception_message(exc)
            self._try_fail(
                job.id,
                error_code=type(exc).__name__.upper(),
                error_message=error_message,
            )
            self._log(
                level="error",
                event="job_failed",
                job_id=job.id,
                data={
                    "job_kind": job.kind,
                    "error_code": type(exc).__name__.upper(),
                    "error_message": error_message,
                },
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

    def _log(
        self,
        *,
        level: str,
        event: str,
        job_id: str,
        data: dict[str, object],
    ) -> None:
        if self.logger is None:
            return
        self.logger.write(
            level=level,
            event=event,
            request_id=job_id,
            data=data,
        )


def _safe_http_status_error_message(exc: httpx.HTTPStatusError) -> str:
    detail = ""
    try:
        payload = exc.response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        typed_payload = cast(dict[str, Any], payload)
        error = typed_payload.get("error")
        if isinstance(error, dict):
            typed_error = cast(dict[str, Any], error)
            message = typed_error.get("message") or typed_error.get("code")
            if isinstance(message, str):
                detail = message
        elif isinstance(error, str):
            detail = error
        if not detail:
            message = (
                typed_payload.get("message")
                or typed_payload.get("detail")
                or typed_payload.get("code")
            )
            if isinstance(message, str):
                detail = message
    status = exc.response.status_code
    return f"上游 HTTP {status}{f'：{detail}' if detail else ''}"


def _safe_exception_message(exc: Exception) -> str:
    detail = str(exc).strip()
    if not detail:
        return "任务处理失败"
    redacted = redact_sensitive(detail)
    if not isinstance(redacted, str):
        return "任务处理失败"
    if len(redacted) > 500:
        redacted = f"{redacted[:500]}..."
    return f"任务处理失败：{redacted}"
