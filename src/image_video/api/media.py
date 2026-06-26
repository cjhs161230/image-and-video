"""Controlled media access routes."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse

from image_video.api.base import envelope
from image_video.application.history import HistoryService
from image_video.application.media_uploads import MediaUploadService

router = APIRouter(prefix="/api/v1/media")


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_media(request: Request, file: UploadFile) -> dict[str, Any]:
    service: MediaUploadService = request.app.state.media_upload_service
    return envelope(
        service.save_uploaded_image(
            filename=file.filename or "",
            content=await file.read(),
        )
    )


@router.get("/{media_id}")
def get_media(request: Request, media_id: str) -> FileResponse:
    service: HistoryService = request.app.state.history_service
    path = service.resolve_media_path(media_id)
    if path is None:
        raise HTTPException(status_code=404, detail="媒体不存在")
    return FileResponse(path)


@router.delete("/{media_id}")
def delete_media(
    request: Request,
    media_id: str,
    confirm: bool = Query(default=False),
) -> dict[str, Any]:
    service: HistoryService = request.app.state.history_service
    result = service.delete_media(media_id, confirm=confirm)
    if result["status"] == "confirmation_required":
        raise HTTPException(status_code=409, detail="需要二次确认")
    return envelope(result)
