"""Video project v1 API routes."""

from typing import Any

from fastapi import APIRouter, Request, status
from pydantic import BaseModel

from image_video.api.base import envelope
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


@router.post("", status_code=status.HTTP_201_CREATED)
def create_video_project(request: Request, body: VideoProjectDraftRequest) -> dict[str, Any]:
    service: VideoProjectService = request.app.state.video_project_service
    project_id = service.create_draft(body)
    return envelope({"project_id": project_id, "status": "draft"})


@router.patch("/{project_id}/draft")
def autosave_video_project_draft(
    request: Request, project_id: str, body: VideoProjectDraftRequest
) -> dict[str, Any]:
    service: VideoProjectService = request.app.state.video_project_service
    return envelope(service.update_draft(project_id, body))


@router.post("/{project_id}/storyboard/generate", status_code=status.HTTP_202_ACCEPTED)
def generate_storyboard(request: Request, project_id: str) -> dict[str, Any]:
    service: VideoProjectService = request.app.state.video_project_service
    version_id = service.generate_storyboard(project_id, request.app.state.storyboard_planner)
    return envelope(
        {
            "project_id": project_id,
            "version_id": version_id,
            "status": "awaiting_storyboard_approval",
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
