from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from image_video.application.video_projects import VideoProjectDraftRequest, VideoProjectService
from image_video.infrastructure.database.engine import create_database_engine, initialize_database
from image_video.infrastructure.database.models import VideoProject
from image_video.infrastructure.providers.deepseek import StoryboardPlan


class FakeStoryboardPlanner:
    def __init__(self, plan: StoryboardPlan):
        self.plan = plan
        self.calls: list[Mapping[str, object]] = []

    def create_storyboard(self, request: Mapping[str, object]) -> StoryboardPlan:
        self.calls.append(request)
        return self.plan


def make_service(tmp_path: Path) -> VideoProjectService:
    engine = create_database_engine(tmp_path / "video.db")
    initialize_database(engine)
    return VideoProjectService(engine)


def test_storyboard_plan_requires_first_keyframe_at_zero(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(title="demo", description="walk", reference_images=[])
    )
    planner = FakeStoryboardPlanner(
        StoryboardPlan(
            global_prompt="scene",
            character_lock="hero",
            scene_lock="street",
            camera_lock="wide",
            keyframes=[{"frame": 1, "description": "late", "prompt": "late"}],
            segments=[],
        )
    )

    with pytest.raises(ValueError, match="首个关键帧必须从 0 开始"):
        service.generate_storyboard(project_id, planner)


def test_storyboard_confirmation_applies_reviewed_version(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(title="demo", description="walk", reference_images=[])
    )
    version_id = service.save_storyboard_version(
        project_id,
        source="user",
        plan=StoryboardPlan(
            global_prompt="scene",
            character_lock="hero",
            scene_lock="street",
            camera_lock="wide",
            keyframes=[{"frame": 0, "description": "start", "prompt": "start"}],
            segments=[],
        ),
    )

    service.confirm_storyboard(project_id, version_id)

    with Session(service.engine) as session:
        project = session.get(VideoProject, project_id)
        assert project is not None
        assert project.status == "generating_keyframes"
        assert project.settings["approved_storyboard_version_id"] == version_id
