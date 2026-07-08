"""Archived video project v1 API routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse

from image_video.api.base import error_envelope

router = APIRouter(prefix="/api/v1/video-projects")

ARCHIVED_CODE = "VIDEO_FEATURE_ARCHIVED"
ARCHIVED_MESSAGE = (
    "视频功能已归档，当前默认不可用；恢复请查看 "
    "archive/video_feature_20260708/restore-notes.md"
)


def archived_response(request: Request) -> JSONResponse:
    request_id = request.headers.get("X-Request-ID")
    return JSONResponse(
        status_code=status.HTTP_410_GONE,
        content=error_envelope(
            code=ARCHIVED_CODE,
            message=ARCHIVED_MESSAGE,
            details=None,
            request_id=request_id,
        ),
    )


@router.post("")
def create_video_project_archived(request: Request) -> JSONResponse:
    return archived_response(request)


@router.get("/{project_id}")
def get_video_project_archived(request: Request, project_id: str) -> JSONResponse:
    del project_id
    return archived_response(request)


@router.patch("/{project_id}/draft")
def autosave_video_project_draft_archived(
    request: Request, project_id: str
) -> JSONResponse:
    del project_id
    return archived_response(request)


@router.post("/{project_id}/storyboard/generate")
def generate_storyboard_archived(request: Request, project_id: str) -> JSONResponse:
    del project_id
    return archived_response(request)


@router.post("/{project_id}/storyboard/versions")
def create_storyboard_version_archived(
    request: Request, project_id: str
) -> JSONResponse:
    del project_id
    return archived_response(request)


@router.get("/{project_id}/storyboard/versions")
def list_storyboard_versions_archived(
    request: Request, project_id: str
) -> JSONResponse:
    del project_id
    return archived_response(request)


@router.post("/{project_id}/storyboard/review")
def review_storyboard_version_archived(
    request: Request, project_id: str
) -> JSONResponse:
    del project_id
    return archived_response(request)


@router.post("/{project_id}/storyboard/versions/{version_id}/confirm")
def confirm_storyboard_version_archived(
    request: Request, project_id: str, version_id: str
) -> JSONResponse:
    del project_id, version_id
    return archived_response(request)


@router.post("/{project_id}/keyframes/generate")
def generate_keyframes_archived(request: Request, project_id: str) -> JSONResponse:
    del project_id
    return archived_response(request)


@router.get("/{project_id}/keyframes")
def list_keyframes_archived(request: Request, project_id: str) -> JSONResponse:
    del project_id
    return archived_response(request)


@router.get("/{project_id}/keyframes/{frame}/media")
def get_keyframe_media_archived(
    request: Request,
    project_id: str,
    frame: int,
) -> JSONResponse:
    del project_id, frame
    return archived_response(request)


@router.get("/{project_id}/output")
def get_video_output_archived(request: Request, project_id: str) -> JSONResponse:
    del project_id
    return archived_response(request)


@router.post("/{project_id}/keyframes/{frame}/regenerate")
def regenerate_keyframe_archived(
    request: Request, project_id: str, frame: int
) -> JSONResponse:
    del project_id, frame
    return archived_response(request)


@router.post("/{project_id}/keyframes/confirm")
def confirm_keyframes_archived(request: Request, project_id: str) -> JSONResponse:
    del project_id
    return archived_response(request)


@router.post("/{project_id}/frames/generate")
def generate_frames_archived(request: Request, project_id: str) -> JSONResponse:
    del project_id
    return archived_response(request)


@router.get("/{project_id}/frames/issues")
def list_frame_issues_archived(request: Request, project_id: str) -> JSONResponse:
    del project_id
    return archived_response(request)


@router.post("/{project_id}/frames/{frame}/repair")
def repair_frame_archived(
    request: Request, project_id: str, frame: int
) -> JSONResponse:
    del project_id, frame
    return archived_response(request)


@router.post("/{project_id}/stitch")
def stitch_video_archived(request: Request, project_id: str) -> JSONResponse:
    del project_id
    return archived_response(request)


@router.delete("/{project_id}")
def delete_video_project_archived(
    request: Request,
    project_id: str,
    confirm: bool = Query(default=False),
) -> JSONResponse:
    del project_id, confirm
    return archived_response(request)

