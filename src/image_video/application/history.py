"""Unified history application service."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from image_video.infrastructure.database.models import MediaAsset, VideoProject

HistoryKind = Literal["image", "video"]
Unlink = Callable[[Path], None]


class HistoryService:
    def __init__(self, engine: Engine, *, data_root: Path):
        self.engine = engine
        self.data_root = data_root.resolve()

    def list_history(self, kind: HistoryKind | None = None) -> list[dict[str, object]]:
        with Session(self.engine) as session:
            items: list[dict[str, object]] = []
            if kind in (None, "image"):
                media_assets = session.scalars(
                    select(MediaAsset).order_by(MediaAsset.created_at, MediaAsset.id)
                ).all()
                items.extend(
                    {
                        "id": asset.id,
                        "kind": "image",
                        "path": asset.path,
                        "thumbnail_path": asset.thumbnail_path,
                        "cover_path": asset.thumbnail_path,
                        "created_at": asset.created_at.isoformat(),
                        "log_summary": "状态：completed",
                    }
                    for asset in media_assets
                )
            if kind in (None, "video"):
                projects = session.scalars(
                    select(VideoProject)
                    .where(VideoProject.status == "completed")
                    .order_by(VideoProject.updated_at, VideoProject.id)
                ).all()
                items.extend(
                    {
                        "id": project.id,
                        "kind": "video",
                        "path": project.settings.get("output_video_path", ""),
                        "thumbnail_path": "",
                        "cover_path": project.settings.get("output_video_path", ""),
                        "created_at": project.updated_at.isoformat(),
                        "log_summary": f"状态：{project.status}",
                    }
                    for project in projects
                )
            return items

    def resolve_media_path(self, media_id: str) -> Path | None:
        with Session(self.engine) as session:
            asset = session.get(MediaAsset, media_id)
            if asset is None:
                return None
            path = Path(asset.path).resolve()
            if not path.is_file():
                return None
            try:
                path.relative_to(self.data_root)
            except ValueError:
                return None
            return path

    def delete_media(
        self,
        media_id: str,
        *,
        confirm: bool,
        unlink: Unlink | None = None,
    ) -> dict[str, object]:
        if not confirm:
            return {"id": media_id, "status": "confirmation_required"}
        unlink_file = unlink or Path.unlink
        with Session(self.engine) as session:
            asset = session.get(MediaAsset, media_id)
            if asset is None:
                return {"id": media_id, "status": "missing"}
            paths = {
                path
                for path in [
                    self.resolve_media_path(asset.id),
                    Path(asset.thumbnail_path).resolve(),
                ]
                if path is not None
            }
            try:
                for path in paths:
                    if path.exists():
                        unlink_file(path)
            except OSError as exc:
                return {
                    "id": media_id,
                    "status": "partial_failed",
                    "error": str(exc),
                }
            session.delete(asset)
            session.commit()
            return {"id": media_id, "status": "deleted"}
