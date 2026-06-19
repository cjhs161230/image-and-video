"""Video project draft application service."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from image_video.infrastructure.database.models import (
    VideoProject,
    VideoReferenceImage,
    VideoStoryboardVersion,
)
from image_video.infrastructure.providers.deepseek import StoryboardPlan

ReferenceLabel = Literal["角色", "场景", "风格"]


class VideoReferenceImageInput(BaseModel):
    media_id: str
    label: ReferenceLabel
    note: str = ""


class VideoProjectDraftRequest(BaseModel):
    title: str
    description: str
    reference_images: list[VideoReferenceImageInput] = Field(
        default_factory=list[VideoReferenceImageInput]
    )

    @model_validator(mode="after")
    def validate_reference_count(self) -> VideoProjectDraftRequest:
        if len(self.reference_images) > 8:
            raise ValueError("最多 8 张参考图")
        return self


class StoryboardPlanner(Protocol):
    def create_storyboard(self, request: Mapping[str, object]) -> StoryboardPlan: ...


class VideoProjectService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def create_draft(self, request: VideoProjectDraftRequest) -> str:
        now = datetime.now(UTC)
        project_id = str(uuid4())
        with Session(self.engine) as session:
            session.add(
                VideoProject(
                    id=project_id,
                    title=request.title,
                    description=request.description,
                    status="draft",
                    settings={},
                    created_at=now,
                    updated_at=now,
                )
            )
            for position, reference in enumerate(request.reference_images):
                session.add(
                    VideoReferenceImage(
                        id=str(uuid4()),
                        project_id=project_id,
                        media_id=reference.media_id,
                        label=reference.label,
                        note=reference.note,
                        position=position,
                        created_at=now,
                    )
                )
            session.commit()
        return project_id

    def update_draft(
        self, project_id: str, request: VideoProjectDraftRequest
    ) -> dict[str, object]:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            project = session.get(VideoProject, project_id)
            if project is None:
                raise KeyError(project_id)
            if project.status != "draft":
                raise ValueError("只有草稿状态可自动保存")
            project.title = request.title
            project.description = request.description
            project.updated_at = now
            session.execute(
                delete(VideoReferenceImage).where(
                    VideoReferenceImage.project_id == project_id
                )
            )
            for position, reference in enumerate(request.reference_images):
                session.add(
                    VideoReferenceImage(
                        id=str(uuid4()),
                        project_id=project_id,
                        media_id=reference.media_id,
                        label=reference.label,
                        note=reference.note,
                        position=position,
                        created_at=now,
                    )
                )
            session.commit()
            return {
                "project_id": project_id,
                "status": project.status,
                "title": project.title,
                "reference_count": len(request.reference_images),
            }

    def generate_storyboard(self, project_id: str, planner: StoryboardPlanner) -> str:
        with Session(self.engine) as session:
            project = session.get(VideoProject, project_id)
            if project is None:
                raise KeyError(project_id)
            project.status = "planning"
            project.updated_at = datetime.now(UTC)
            storyboard_request: Mapping[str, object] = {
                "title": project.title,
                "description": project.description,
                "references": self._reference_labels(session, project_id),
            }
            session.commit()

        plan = planner.create_storyboard(storyboard_request)
        self._validate_storyboard(plan)
        version_id = self.save_storyboard_version(project_id, source="ai", plan=plan)
        with Session(self.engine) as session:
            project = session.get(VideoProject, project_id)
            if project is None:
                raise KeyError(project_id)
            project.status = "awaiting_storyboard_approval"
            project.updated_at = datetime.now(UTC)
            session.commit()
        return version_id

    def save_storyboard_version(
        self,
        project_id: str,
        *,
        source: Literal["ai", "user"],
        plan: StoryboardPlan,
        suggestion: str = "",
    ) -> str:
        self._validate_storyboard(plan)
        now = datetime.now(UTC)
        version_id = str(uuid4())
        with Session(self.engine) as session:
            if session.get(VideoProject, project_id) is None:
                raise KeyError(project_id)
            latest_version = session.scalar(
                select(func.max(VideoStoryboardVersion.version)).where(
                    VideoStoryboardVersion.project_id == project_id
                )
            )
            session.add(
                VideoStoryboardVersion(
                    id=version_id,
                    project_id=project_id,
                    version=(latest_version or 0) + 1,
                    source=source,
                    plan=plan.model_dump(),
                    suggestion=suggestion,
                    created_at=now,
                )
            )
            session.commit()
        return version_id

    def list_storyboard_versions(self, project_id: str) -> list[dict[str, object]]:
        with Session(self.engine) as session:
            if session.get(VideoProject, project_id) is None:
                raise KeyError(project_id)
            versions = session.scalars(
                select(VideoStoryboardVersion)
                .where(VideoStoryboardVersion.project_id == project_id)
                .order_by(VideoStoryboardVersion.version)
            ).all()
            return [
                {
                    "version_id": version.id,
                    "version": version.version,
                    "source": version.source,
                    "suggestion": version.suggestion,
                    "plan": version.plan,
                    "created_at": version.created_at.isoformat(),
                }
                for version in versions
            ]

    def confirm_storyboard(self, project_id: str, version_id: str) -> None:
        with Session(self.engine) as session:
            project = session.get(VideoProject, project_id)
            version = session.get(VideoStoryboardVersion, version_id)
            if project is None or version is None or version.project_id != project_id:
                raise KeyError(project_id)
            project.status = "generating_keyframes"
            project.settings = {
                **project.settings,
                "approved_storyboard_version_id": version_id,
            }
            project.updated_at = datetime.now(UTC)
            session.commit()

    @staticmethod
    def _validate_storyboard(plan: StoryboardPlan) -> None:
        frames = [keyframe.frame for keyframe in plan.keyframes]
        if frames[0] != 0:
            raise ValueError("首个关键帧必须从 0 开始")
        if frames != sorted(set(frames)):
            raise ValueError("关键帧必须按帧号递增且不能重复")
        for segment in plan.segments:
            if segment.end_frame <= segment.start_frame:
                raise ValueError("片段结束帧必须大于开始帧")

    @staticmethod
    def _reference_labels(session: Session, project_id: str) -> list[dict[str, str]]:
        references = session.scalars(
            select(VideoReferenceImage)
            .where(VideoReferenceImage.project_id == project_id)
            .order_by(VideoReferenceImage.position)
        ).all()
        return [
            {"label": reference.label, "note": reference.note}
            for reference in references
        ]
