"""Unified history v1 API routes."""

from typing import Any, Literal

from fastapi import APIRouter, Query, Request

from image_video.api.base import envelope
from image_video.application.history import HistoryService

router = APIRouter(prefix="/api/v1/history")


@router.get("")
def list_history(
    request: Request,
    kind: Literal["image", "video"] | None = Query(default=None),
) -> dict[str, Any]:
    service: HistoryService = request.app.state.history_service
    return envelope(service.list_history(kind=kind))
