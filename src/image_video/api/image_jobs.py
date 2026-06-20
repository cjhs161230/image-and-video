"""Image job v1 API routes."""

from typing import Any

from fastapi import APIRouter, Request, status

from image_video.api.base import envelope
from image_video.application.image_jobs import ImageJobRequest, ImageJobService
from image_video.infrastructure.database.queue import JobQueue

router = APIRouter(prefix="/api/v1/image-jobs")


def _queue(request: Request) -> JobQueue:
    return request.app.state.job_queue


def _job_data(request: Request, job_id: str) -> dict[str, Any]:
    job = _queue(request).get(job_id)
    media = request.app.state.media_repository.for_job(job_id)
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status.value,
        "attempt_count": job.attempt_count,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "media": [
            {"id": asset.id, "url": f"/api/v1/media/{asset.id}"}
            for asset in media
        ],
    }


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_image_job(request: Request, body: ImageJobRequest) -> dict[str, Any]:
    service: ImageJobService = request.app.state.image_job_service
    return envelope({"job_id": service.submit(body), "status": "queued"})


@router.get("/{job_id}")
def get_image_job(request: Request, job_id: str) -> dict[str, Any]:
    return envelope(_job_data(request, job_id))


@router.post("/{job_id}/pause")
def pause_image_job(request: Request, job_id: str) -> dict[str, Any]:
    _queue(request).pause(job_id)
    return envelope(_job_data(request, job_id))


@router.post("/{job_id}/resume")
def resume_image_job(request: Request, job_id: str) -> dict[str, Any]:
    _queue(request).resume(job_id)
    return envelope(_job_data(request, job_id))


@router.post("/{job_id}/cancel")
def cancel_image_job(request: Request, job_id: str) -> dict[str, Any]:
    _queue(request).cancel(job_id)
    return envelope(_job_data(request, job_id))
