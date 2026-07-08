"""Base v1 API routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request

from image_video.application.history import HistoryService
from image_video.infrastructure.config import PublicSettings, SettingsStore

router = APIRouter(prefix="/api/v1")

MODELS = [
    {"key": "wan2.7-image", "provider": "dashscope"},
    {"key": "wan2.7-image-pro", "provider": "dashscope"},
    {"key": "qwen-image-2.0", "provider": "dashscope"},
    {"key": "qwen-image-2.0-pro", "provider": "dashscope"},
    {"key": "gpt-image-2", "provider": "matsca"},
]


def envelope(data: Any, request_id: str | None = None) -> dict[str, Any]:
    return {"data": data, "error": None, "request_id": request_id or str(uuid4())}


def error_envelope(
    *,
    code: str,
    message: str,
    details: Any = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "data": None,
        "error": {"code": code, "message": message, "details": details},
        "request_id": request_id or str(uuid4()),
    }


@router.get("/health")
def health() -> dict[str, Any]:
    return envelope({"status": "ok"})


@router.get("/models")
def models() -> dict[str, Any]:
    return envelope(MODELS)


@router.get("/config/status")
def config_status(request: Request) -> dict[str, Any]:
    return envelope(request.app.state.secrets.status())


@router.get("/estimates/storage")
def storage_estimate(request: Request) -> dict[str, Any]:
    service: HistoryService = request.app.state.history_service
    return envelope(service.storage_estimate())


@router.get("/settings")
def get_settings(request: Request) -> dict[str, Any]:
    return envelope(request.app.state.settings_store.load().model_dump())


@router.patch("/settings")
def update_settings(request: Request, settings: PublicSettings) -> dict[str, Any]:
    store: SettingsStore = request.app.state.settings_store
    store.save(settings)
    return envelope(settings.model_dump())


def default_settings_store(data_root: Path | None = None) -> SettingsStore:
    return SettingsStore((data_root or Path("data")) / "settings.json")
