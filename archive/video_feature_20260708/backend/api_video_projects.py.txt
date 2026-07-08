"""Video project v1 API routes."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from image_video.api.base import envelope
from image_video.application.history import HistoryService
from image_video.application.video_projects import (
    VideoProjectDraftRequest,
    VideoProjectService,
)
from image_video.infrastructure.providers.deepseek import StoryboardPlan

router = APIRouter(prefix="/api/v1/video-projects")


class StoryboardVersionRequest(BaseModel):
    source: str
    plan: StoryboardPlan
    suggestion: str = ""


class StoryboardReviewRequest(BaseModel):
    version_id: str


@router.post("", status_code=status.HTTP_201_CREATED)
def create_video_project(request: Request, body: VideoProjectDraftRequest) -> dict[str, Any]:
    service: VideoProjectService = request.app.state.video_project_service
    project_id = service.create_draft(body)
    return envelope({"project_id": project_id, "status": "draft"})


@router.get("/{project_id}")
def get_video_project(request: Request, project_id: str) -> dict[str, Any]:
    service: VideoProjectService = request.app.state.video_project_service
    return envelope(service.get_project_summary(project_id))


@router.patch("/{project_id}/draft")
def autosave_video_project_draft(
    request: Request, project_id: str, body: VideoProjectDraftRequest
) -> dict[str, Any]:
    service: VideoProjectService = request.app.state.video_project_service
    return envelope(service.update_draft(project_id, body))


@router.post("/{project_id}/storyboard/generate", status_code=status.HTTP_202_ACCEPTED)
def generate_storyboard(request: Request, project_id: str) -> dict[str, Any]:
    service: VideoProjectService = request.app.state.video_project_service
    job_id = service.request_storyboard_generation(
        project_id,
        lambda: request.app.state.job_queue.enqueue(
            "video.storyboard.generate", {"project_id": project_id}
        ),
    )
    return envelope(
        {
            "project_id": project_id,
            "job_id": job_id,
            "status": "queued",
        }
    )


@router.post("/{project_id}/storyboard/versions", status_code=status.HTTP_201_CREATED)
def create_storyboard_version(
    request: Request, project_id: str, body: StoryboardVersionRequest
) -> dict[str, Any]:
    service: VideoProjectService = request.app.state.video_project_service
    version_id = service.save_storyboard_version(
        project_id,
        source="user" if body.source == "user" else "ai",
        plan=body.plan,
        suggestion=body.suggestion,
    )
    return envelope({"project_id": project_id, "version_id": version_id})


@router.get("/{project_id}/storyboard/versions")
def list_storyboard_versions(request: Request, project_id: str) -> dict[str, Any]:
    service: VideoProjectService = request.app.state.video_project_service
    return envelope(service.list_storyboard_versions(project_id))


@router.post("/{project_id}/storyboard/review", status_code=status.HTTP_202_ACCEPTED)
def review_storyboard_version(
    request: Request,
    project_id: str,
    body: StoryboardReviewRequest,
) -> dict[str, Any]:
    service: VideoProjectService = request.app.state.video_project_service
    job_id = service.request_storyboard_review(
        project_id,
        version_id=body.version_id,
        enqueue=lambda: request.app.state.job_queue.enqueue(
            "video.storyboard.review",
            {"project_id": project_id, "version_id": body.version_id},
        ),
    )
    return envelope(
        {
            "project_id": project_id,
            "version_id": body.version_id,
            "job_id": job_id,
            "status": "queued",
        }
    )


@router.post("/{project_id}/storyboard/versions/{version_id}/confirm")
def confirm_storyboard_version(
    request: Request, project_id: str, version_id: str
) -> dict[str, Any]:
    service: VideoProjectService = request.app.state.video_project_service
    service.confirm_storyboard(project_id, version_id)
    return envelope(
        {
            "project_id": project_id,
            "version_id": version_id,
            "status": "generating_keyframes",
        }
    )


@router.post("/{project_id}/keyframes/generate", status_code=status.HTTP_202_ACCEPTED)
def generate_keyframes(request: Request, project_id: str) -> dict[str, Any]:
    service: VideoProjectService = request.app.state.video_project_service
    job_id = service.request_keyframe_generation(
        project_id,
        lambda: request.app.state.job_queue.enqueue(
            "video.keyframes.generate", {"project_id": project_id}
        ),
    )
    return envelope(
        {
            "project_id": project_id,
            "job_id": job_id,
            "status": "queued",
        }
    )


@router.get("/{project_id}/keyframes")
def list_keyframes(request: Request, project_id: str) -> dict[str, Any]:
    service: VideoProjectService = request.app.state.video_project_service
    return envelope(service.list_keyframes(project_id))


@router.get("/{project_id}/keyframes/{frame}/media")
def get_keyframe_media(
    request: Request,
    project_id: str,
    frame: int,
) -> FileResponse:
    service: HistoryService = request.app.state.history_service
    path = service.resolve_video_keyframe_path(project_id, frame)
    if path is None:
        raise KeyError(project_id)
    return FileResponse(path)


@router.get("/{project_id}/output")
def get_video_output(request: Request, project_id: str) -> FileResponse:
    service: HistoryService = request.app.state.history_service
    path = service.resolve_video_output_path(project_id)
    if path is None:
        raise KeyError(project_id)
    return FileResponse(path, media_type="video/mp4")


@router.post(
    "/{project_id}/keyframes/{frame}/regenerate",
    status_code=status.HTTP_202_ACCEPTED,
)
def regenerate_keyframe(request: Request, project_id: str, frame: int) -> dict[str, Any]:
    service: VideoProjectService = request.app.state.video_project_service
    job_id = service.request_keyframe_regeneration(
        project_id,
        frame=frame,
        enqueue=lambda: request.app.state.job_queue.enqueue(
            "video.keyframe.regenerate",
            {"project_id": project_id, "frame": frame},
        ),
    )
    return envelope(
        {"project_id": project_id, "frame": frame, "job_id": job_id, "status": "queued"}
    )


@router.post("/{project_id}/keyframes/confirm")
def confirm_keyframes(request: Request, project_id: str) -> dict[str, Any]:
    service: VideoProjectService = request.app.state.video_project_service
    service.confirm_keyframes(project_id)
    return envelope({"project_id": project_id, "status": "generating_frames"})


@router.post("/{project_id}/frames/generate", status_code=status.HTTP_202_ACCEPTED)
def generate_frames(request: Request, project_id: str) -> dict[str, Any]:
    service: VideoProjectService = request.app.state.video_project_service
    job_id = service.request_frame_generation(
        project_id,
        lambda: request.app.state.job_queue.enqueue(
            "video.frames.generate", {"project_id": project_id}
        ),
    )
    return envelope({"project_id": project_id, "job_id": job_id, "status": "queued"})


@router.get("/{project_id}/frames/issues")
def list_frame_issues(request: Request, project_id: str) -> dict[str, Any]:
    service: VideoProjectService = request.app.state.video_project_service
    return envelope(service.list_frame_issues(project_id))


@router.post("/{project_id}/frames/{frame}/repair", status_code=status.HTTP_202_ACCEPTED)
def repair_frame(request: Request, project_id: str, frame: int) -> dict[str, Any]:
    service: VideoProjectService = request.app.state.video_project_service
    job_id = service.request_frame_repair(
        project_id,
        frame=frame,
        enqueue=lambda: request.app.state.job_queue.enqueue(
            "video.frame.repair", {"project_id": project_id, "frame": frame}
        )
    )
    return envelope(
        {"project_id": project_id, "frame": frame, "job_id": job_id, "status": "queued"}
    )


@router.post("/{project_id}/stitch", status_code=status.HTTP_202_ACCEPTED)
def stitch_video(request: Request, project_id: str) -> dict[str, Any]:
    service: VideoProjectService = request.app.state.video_project_service
    settings = request.app.state.settings_store.load()
    job_id = service.request_stitch_video(
        project_id,
        lambda: request.app.state.job_queue.enqueue(
            "video.stitch",
            {"project_id": project_id, "ffmpeg_path": settings.ffmpeg_path},
        )
    )
    return envelope({"project_id": project_id, "job_id": job_id, "status": "queued"})


@router.delete("/{project_id}")
def delete_video_project(
    request: Request,
    project_id: str,
    confirm: bool = Query(default=False),
) -> dict[str, Any]:
    service: HistoryService = request.app.state.history_service
    result = service.delete_video_project(project_id, confirm=confirm)
    if result["status"] == "confirmation_required":
        raise HTTPException(status_code=409, detail="需要二次确认")
    return envelope(result)
