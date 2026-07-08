"""Unified history application service."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Literal

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from image_video.infrastructure.database.models import (
    Job,
    JobEvent,
    MediaAsset,
    VideoFrame,
    VideoKeyframe,
    VideoProject,
)

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
                        "media_url": f"/api/v1/media/{asset.id}",
                        "thumbnail_url": f"/api/v1/media/{asset.id}",
                        "cover_url": f"/api/v1/media/{asset.id}",
                        "created_at": asset.created_at.isoformat(),
                        "log_summary": self._job_summary(session, asset.job_id),
                    }
                    for asset in media_assets
                )
            if kind in (None, "video"):
                projects = session.scalars(
                    select(VideoProject).order_by(
                        VideoProject.updated_at.desc(), VideoProject.id.desc()
                    )
                ).all()
                for project in projects:
                    media_url = ""
                    if self._safe_video_output(project) is not None:
                        media_url = f"/api/v1/video-projects/{project.id}/output"
                    latest_job = self._latest_project_job(session, project)
                    cover_keyframe = session.scalar(
                        select(VideoKeyframe)
                        .where(
                            VideoKeyframe.project_id == project.id,
                            VideoKeyframe.status == "completed",
                        )
                        .order_by(VideoKeyframe.frame)
                    )
                    cover_url = ""
                    if (
                        cover_keyframe is not None
                        and self._safe_data_file(cover_keyframe.path) is not None
                    ):
                        cover_url = (
                            f"/api/v1/video-projects/{project.id}"
                            f"/keyframes/{cover_keyframe.frame}/media"
                        )
                    items.append(
                        {
                            "id": project.id,
                            "kind": "video",
                            "status": project.status,
                            "title": project.title,
                            "description": project.description,
                            "project_url": f"/api/v1/video-projects/{project.id}",
                            "can_continue": False,
                            "archived_message": "视频功能已归档，当前默认不可用。",
                            "latest_job_status": (
                                latest_job.status.value if latest_job is not None else ""
                            ),
                            "latest_job_error": (
                                latest_job.error_message
                                or latest_job.error_code
                                or ""
                                if latest_job is not None
                                else ""
                            ),
                            "media_url": media_url,
                            "thumbnail_url": cover_url,
                            "cover_url": cover_url,
                            "created_at": project.updated_at.isoformat(),
                            "updated_at": project.updated_at.isoformat(),
                            "log_summary": self._project_job_summary(
                                session, project, latest_job=latest_job
                            ),
                        }
                    )
            return items

    @staticmethod
    def _job_summary(session: Session, job_id: str) -> str:
        job = session.get(Job, job_id)
        if job is None:
            return "任务记录缺失"
        latest_event = session.scalar(
            select(JobEvent)
            .where(JobEvent.job_id == job_id)
            .order_by(JobEvent.id.desc())
            .limit(1)
        )
        summary = f"任务：{job.status.value}"
        if latest_event is not None:
            summary += f"；最近事件：{latest_event.event}"
        if job.error_code:
            summary += f"；错误：{job.error_code}"
        return summary

    @classmethod
    def _project_job_summary(
        cls, session: Session, project: VideoProject, *, latest_job: Job | None = None
    ) -> str:
        if latest_job is not None:
            return cls._job_summary(session, latest_job.id)
        latest_job = cls._latest_project_job(session, project)
        if latest_job is not None:
            return cls._job_summary(session, latest_job.id)
        return f"状态：{project.status}"

    @staticmethod
    def _latest_project_job(session: Session, project: VideoProject) -> Job | None:
        jobs = session.scalars(
            select(Job)
            .where(Job.kind.like("video.%"))
            .order_by(Job.updated_at.desc(), Job.id.desc())
        ).all()
        for job in jobs:
            if job.payload.get("project_id") == project.id:
                return job
        return None

    def resolve_video_keyframe_path(self, project_id: str, frame: int) -> Path | None:
        with Session(self.engine) as session:
            keyframe = session.scalar(
                select(VideoKeyframe).where(
                    VideoKeyframe.project_id == project_id,
                    VideoKeyframe.frame == frame,
                    VideoKeyframe.status == "completed",
                )
            )
            if keyframe is None:
                return None
            return self._safe_data_file(keyframe.path)

    def resolve_media_path(self, media_id: str) -> Path | None:
        with Session(self.engine) as session:
            asset = session.get(MediaAsset, media_id)
            if asset is None:
                return None
            return self._safe_data_file(asset.path)

    def resolve_video_output_path(self, project_id: str) -> Path | None:
        with Session(self.engine) as session:
            project = session.get(VideoProject, project_id)
            if project is None:
                return None
            return self._safe_video_output(project)

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
            media_path = self._safe_data_file(asset.path)
            thumbnail_path = self._safe_data_file(asset.thumbnail_path)
            if media_path is None or thumbnail_path is None:
                return {
                    "id": media_id,
                    "status": "partial_failed",
                    "error": "媒体文件路径不安全或文件不存在",
                }
            paths = {media_path, thumbnail_path}
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

    def delete_video_project(
        self,
        project_id: str,
        *,
        confirm: bool,
        unlink: Unlink | None = None,
    ) -> dict[str, object]:
        if not confirm:
            return {"id": project_id, "status": "confirmation_required"}
        unlink_file = unlink or Path.unlink
        with Session(self.engine) as session:
            project = session.get(VideoProject, project_id)
            if project is None:
                return {"id": project_id, "status": "missing"}
            paths = self._video_project_paths(session, project)
            if paths is None:
                return {
                    "id": project_id,
                    "status": "partial_failed",
                    "error": "视频项目文件路径不安全或文件不存在",
                }
            try:
                for path in paths:
                    if path.exists():
                        unlink_file(path)
                project_dir = (self.data_root / "video_projects" / project_id).resolve()
                if project_dir.exists():
                    for directory in sorted(
                        [item for item in project_dir.rglob("*") if item.is_dir()],
                        reverse=True,
                    ):
                        with suppress(OSError):
                            directory.rmdir()
                    with suppress(OSError):
                        project_dir.rmdir()
            except OSError as exc:
                return {"id": project_id, "status": "partial_failed", "error": str(exc)}
            session.delete(project)
            session.commit()
            return {"id": project_id, "status": "deleted"}

    def storage_estimate(self) -> dict[str, object]:
        with Session(self.engine) as session:
            image_sizes = [
                path.stat().st_size
                for asset in session.scalars(select(MediaAsset)).all()
                if (path := self._safe_data_file(asset.path)) is not None
            ]
            frame_sizes = [
                path.stat().st_size
                for keyframe in session.scalars(
                    select(VideoKeyframe).where(VideoKeyframe.status == "completed")
                ).all()
                if (path := self._safe_data_file(keyframe.path)) is not None
            ]
            frame_sizes.extend(
                path.stat().st_size
                for frame in session.scalars(
                    select(VideoFrame).where(VideoFrame.status == "completed")
                ).all()
                if (path := self._safe_data_file(frame.path)) is not None
            )
            output_sizes = [
                path.stat().st_size
                for project in session.scalars(select(VideoProject)).all()
                if (path := self._safe_video_output(project)) is not None
            ]
        if not image_sizes and not frame_sizes and not output_sizes:
            return {
                "source": "fallback",
                "image_mb_per_item": 12,
                "video_frame_mb_per_item": 12,
                "video_output_mb_per_project": 0,
                "sample_counts": {"images": 0, "video_frames": 0, "video_outputs": 0},
            }
        return {
            "source": "real",
            "image_mb_per_item": self._average_mb(image_sizes, fallback=12),
            "video_frame_mb_per_item": self._average_mb(frame_sizes, fallback=12),
            "video_output_mb_per_project": self._average_mb(output_sizes, fallback=0),
            "sample_counts": {
                "images": len(image_sizes),
                "video_frames": len(frame_sizes),
                "video_outputs": len(output_sizes),
            },
        }

    def _safe_video_output(self, project: VideoProject) -> Path | None:
        output_path = project.settings.get("output_video_path")
        if not isinstance(output_path, str) or not output_path.lower().endswith(".mp4"):
            return None
        return self._safe_data_file(output_path)

    def _video_project_paths(
        self, session: Session, project: VideoProject
    ) -> set[Path] | None:
        paths: set[Path] = set()
        output_path = project.settings.get("output_video_path")
        if isinstance(output_path, str):
            safe_output = self._safe_video_output(project)
            if safe_output is None:
                return None
            paths.add(safe_output)
        for keyframe in session.scalars(
            select(VideoKeyframe).where(VideoKeyframe.project_id == project.id)
        ).all():
            safe_path = self._safe_data_file(keyframe.path)
            if safe_path is None:
                return None
            paths.add(safe_path)
        for frame in session.scalars(
            select(VideoFrame).where(VideoFrame.project_id == project.id)
        ).all():
            safe_path = self._safe_data_file(frame.path)
            if safe_path is None:
                return None
            paths.add(safe_path)
        return paths

    def _safe_data_file(self, value: str) -> Path | None:
        path = Path(value).resolve()
        if not path.is_file():
            return None
        try:
            path.relative_to(self.data_root)
        except ValueError:
            return None
        return path

    @staticmethod
    def _average_mb(values: list[int], *, fallback: float) -> float:
        if not values:
            return fallback
        return round(sum(values) / len(values) / 1024 / 1024, 4)
