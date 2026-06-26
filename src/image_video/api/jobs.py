"""Unified persistent job v1 API routes."""

from typing import Any

from fastapi import APIRouter, Request

from image_video.api.base import envelope
from image_video.infrastructure.database.queue import JobQueue

router = APIRouter(prefix="/api/v1/jobs")


def _queue(request: Request) -> JobQueue:
    return request.app.state.job_queue


def _job_data(queue: JobQueue, job_id: str) -> dict[str, Any]:
    job = queue.get(job_id)
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status.value,
        "attempt_count": job.attempt_count,
        "error_code": job.error_code,
        "error_message": job.error_message,
    }


@router.get("/{job_id}")
def get_job(request: Request, job_id: str) -> dict[str, Any]:
    return envelope(_job_data(_queue(request), job_id))


@router.post("/{job_id}/pause")
def pause_job(request: Request, job_id: str) -> dict[str, Any]:
    queue = _queue(request)
    queue.pause(job_id)
    return envelope(_job_data(queue, job_id))


@router.post("/{job_id}/resume")
def resume_job(request: Request, job_id: str) -> dict[str, Any]:
    queue = _queue(request)
    queue.resume(job_id)
    return envelope(_job_data(queue, job_id))


@router.post("/{job_id}/cancel")
def cancel_job(request: Request, job_id: str) -> dict[str, Any]:
    queue = _queue(request)
    queue.cancel(job_id)
    return envelope(_job_data(queue, job_id))
