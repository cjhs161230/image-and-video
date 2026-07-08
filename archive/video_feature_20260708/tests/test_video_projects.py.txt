from __future__ import annotations

import threading
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from image_video.application.video_projects import (
    MatscaFrameGenerator,
    MatscaKeyframeGenerator,
    VideoProjectDraftRequest,
    VideoProjectService,
)
from image_video.infrastructure.database.engine import create_database_engine, initialize_database
from image_video.infrastructure.database.models import (
    VideoFrame,
    VideoKeyframe,
    VideoProject,
)
from image_video.infrastructure.providers.deepseek import StoryboardPlan
from image_video.infrastructure.providers.matsca import GeneratedImage, MatscaImageTask


class FakeStoryboardPlanner:
    def __init__(self, plan: StoryboardPlan):
        self.plan = plan
        self.calls: list[dict[str, object]] = []

    def create_storyboard(self, request: dict[str, object]) -> StoryboardPlan:
        self.calls.append(request)
        return self.plan


class FakeStoryboardReviewer:
    def __init__(self, plan: StoryboardPlan):
        self.plan = plan
        self.calls: list[dict[str, object]] = []

    def review_storyboard(self, request: dict[str, object]) -> StoryboardPlan:
        self.calls.append(request)
        return self.plan


class FakeMatscaProvider:
    def generate(self, **kwargs: object) -> list[GeneratedImage]:
        assert kwargs["prompt"] == "keyframe prompt"
        assert kwargs["output_format"] == "png"
        assert kwargs["n"] == 1
        return [GeneratedImage(content=b"png-bytes")]


class FakeMatscaUrlProvider:
    def generate(self, **kwargs: object) -> list[GeneratedImage]:
        del kwargs
        return [GeneratedImage(url="https://cdn.test/keyframe.png")]


class RecordingMatscaEditProvider:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    def edit(self, **kwargs: object) -> list[GeneratedImage]:
        self.calls.append(dict(kwargs))
        return [GeneratedImage(content=b"generated-frame")]


class RecordingFrameGenerator:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        *,
        frame: int,
        prompt: str,
        references: list[str],
        previous_frame_path: str | None,
        anchor_frame_paths: list[str],
    ) -> bytes:
        self.calls.append(
            {
                "frame": frame,
                "prompt": prompt,
                "references": references,
                "previous_frame_path": previous_frame_path,
                "anchor_frame_paths": anchor_frame_paths,
            }
        )
        return f"frame-{frame}".encode()


class RecordingFfmpegRunner:
    def __init__(self):
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str]) -> None:
        self.commands.append(command)


def make_service(tmp_path: Path) -> VideoProjectService:
    engine = create_database_engine(tmp_path / "video.db")
    initialize_database(engine)
    return VideoProjectService(
        engine, data_root=tmp_path / "data", validate_image_saves=False
    )


def png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (16, 16), "blue").save(output, format="PNG")
    return output.getvalue()


def test_video_outputs_are_written_under_configured_data_root(
    tmp_path: Path,
) -> None:
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
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start"},
                {"frame": 2, "description": "end", "prompt": "end"},
            ],
            segments=[{"start_frame": 0, "end_frame": 2, "motion": "walk"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)

    keyframes = service.generate_keyframes(project_id, generator=lambda prompt: b"png")

    expected_root = (tmp_path / "data").resolve()
    assert all(
        Path(str(item["path"])).resolve().is_relative_to(expected_root)
        for item in keyframes
    )


def test_video_image_save_validates_image_by_default(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "video.db")
    initialize_database(engine)
    service = VideoProjectService(engine, data_root=tmp_path / "data")
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

    with pytest.raises(ValueError, match="图片保存失败"):
        service.generate_keyframes(project_id, generator=lambda prompt: b"not image")

    generated = service.generate_keyframes(project_id, generator=lambda prompt: png_bytes())

    assert generated[0]["status"] == "completed"


def test_matsca_frame_generator_uses_continuity_references_within_limit(
    tmp_path: Path,
) -> None:
    start = tmp_path / "start.png"
    end = tmp_path / "end.png"
    previous = tmp_path / "previous.png"
    start.write_bytes(b"start")
    end.write_bytes(b"end")
    previous.write_bytes(b"previous")
    provider = RecordingMatscaEditProvider()
    reference_bytes = {f"ref-{index}": f"ref-{index}".encode() for index in range(8)}
    generator = MatscaFrameGenerator(
        provider,
        reference_loader=lambda ids: [reference_bytes[item] for item in ids],
    )

    first = generator(
        frame=1,
        prompt="walk",
        references=[f"ref-{index}" for index in range(7)],
        previous_frame_path=start.as_posix(),
        anchor_frame_paths=[start.as_posix(), end.as_posix()],
    )
    later = generator(
        frame=2,
        prompt="walk",
        references=[f"ref-{index}" for index in range(6)],
        previous_frame_path=previous.as_posix(),
        anchor_frame_paths=[start.as_posix(), end.as_posix()],
    )

    assert first == b"generated-frame"
    assert later == b"generated-frame"
    assert provider.calls[0]["images"] == [
        b"start",
        *[reference_bytes[f"ref-{index}"] for index in range(7)],
    ]
    assert provider.calls[1]["images"] == [
        b"end",
        b"previous",
        *[reference_bytes[f"ref-{index}"] for index in range(6)],
    ]


def test_matsca_frame_generator_creates_and_resumes_async_edit_task(
    tmp_path: Path,
) -> None:
    start = tmp_path / "start.png"
    end = tmp_path / "end.png"
    start.write_bytes(b"start")
    end.write_bytes(b"end")

    class AsyncEditProvider:
        def __init__(self):
            self.created = 0

        def create_edit_task(self, **kwargs: object) -> MatscaImageTask:
            self.created += 1
            assert kwargs["images"] == [b"start", b"reference"]
            return MatscaImageTask(id="task-frame", status="queued", images=[])

        def get_image_task(self, task_id: str) -> MatscaImageTask:
            assert task_id == "task-frame"
            return MatscaImageTask(
                id=task_id,
                status="completed",
                images=[GeneratedImage(content=b"async-frame")],
            )

    provider = AsyncEditProvider()
    generator = MatscaFrameGenerator(
        provider,
        reference_loader=lambda ids: [b"reference" for _ in ids],
        poll_interval=0,
        poll_timeout=1,
    )
    created_ids: list[str] = []

    first = generator.generate(
        frame=1,
        prompt="walk",
        references=["ref-1"],
        previous_frame_path=start.as_posix(),
        anchor_frame_paths=[start.as_posix(), end.as_posix()],
        task_id=None,
        on_task_created=created_ids.append,
    )
    resumed = generator.generate(
        frame=1,
        prompt="walk",
        references=["ref-1"],
        previous_frame_path=start.as_posix(),
        anchor_frame_paths=[start.as_posix(), end.as_posix()],
        task_id="task-frame",
        on_task_created=lambda task_id: pytest.fail(task_id),
    )

    assert first == b"async-frame"
    assert resumed == b"async-frame"
    assert created_ids == ["task-frame"]
    assert provider.created == 1


def test_matsca_frame_generator_recreates_interrupted_task_with_same_client_task_id(
    tmp_path: Path,
) -> None:
    start = tmp_path / "start.png"
    end = tmp_path / "end.png"
    start.write_bytes(b"start")
    end.write_bytes(b"end")

    class InterruptedProvider:
        def __init__(self):
            self.created_with: list[str | None] = []
            self.checked = 0

        def create_edit_task(self, **kwargs: object) -> MatscaImageTask:
            self.created_with.append(kwargs.get("client_task_id"))
            return MatscaImageTask(id="task-frame-resubmitted", status="queued", images=[])

        def get_image_task(self, task_id: str) -> MatscaImageTask:
            self.checked += 1
            if self.checked == 1:
                assert task_id == "task-frame"
                return MatscaImageTask(
                    id=task_id,
                    status="failed",
                    error="服务已重启，图片任务已中断；请使用相同 client_task_id 重新提交",
                    images=[],
                )
            assert task_id == "task-frame-resubmitted"
            return MatscaImageTask(
                id=task_id,
                status="completed",
                images=[GeneratedImage(content=b"resubmitted-frame")],
            )

    provider = InterruptedProvider()
    generator = MatscaFrameGenerator(
        provider,
        reference_loader=lambda ids: [b"reference" for _ in ids],
        poll_interval=0,
        poll_timeout=1,
    )
    created_ids: list[str] = []

    content = generator.generate(
        frame=1,
        prompt="walk",
        references=["ref-1"],
        previous_frame_path=start.as_posix(),
        anchor_frame_paths=[start.as_posix(), end.as_posix()],
        task_id="task-frame",
        on_task_created=created_ids.append,
    )

    assert content == b"resubmitted-frame"
    assert provider.created_with == ["task-frame"]
    assert created_ids == ["task-frame-resubmitted"]


def test_matsca_frame_generator_downloads_async_url_result(tmp_path: Path) -> None:
    start = tmp_path / "start.png"
    end = tmp_path / "end.png"
    start.write_bytes(b"start")
    end.write_bytes(b"end")

    class AsyncUrlProvider:
        def create_edit_task(self, **kwargs: object) -> MatscaImageTask:
            del kwargs
            return MatscaImageTask(id="task-frame-url", status="queued", images=[])

        def get_image_task(self, task_id: str) -> MatscaImageTask:
            assert task_id == "task-frame-url"
            return MatscaImageTask(
                id=task_id,
                status="completed",
                images=[GeneratedImage(url="https://cdn.test/frame.png")],
            )

    generator = MatscaFrameGenerator(
        AsyncUrlProvider(),
        reference_loader=lambda ids: [b"reference" for _ in ids],
        downloader=lambda url: f"downloaded:{url}".encode(),
        poll_interval=0,
        poll_timeout=1,
    )

    content = generator.generate(
        frame=1,
        prompt="walk",
        references=["ref-1"],
        previous_frame_path=start.as_posix(),
        anchor_frame_paths=[start.as_posix(), end.as_posix()],
        task_id=None,
        on_task_created=lambda task_id: None,
    )

    assert content == b"downloaded:https://cdn.test/frame.png"


@pytest.mark.parametrize(
    ("failure", "expected_status"),
    [
        (RuntimeError("provider failed"), "failed"),
        (TimeoutError("result uncertain"), "needs_attention"),
    ],
)
def test_storyboard_failure_leaves_recoverable_project_status(
    tmp_path: Path,
    failure: Exception,
    expected_status: str,
) -> None:
    service = make_service(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(title="demo", description="walk", reference_images=[])
    )

    class FailingPlanner:
        def create_storyboard(self, request: dict[str, object]) -> StoryboardPlan:
            del request
            raise failure

    with pytest.raises(type(failure)):
        service.generate_storyboard(project_id, FailingPlanner())

    with Session(service.engine) as session:
        project = session.get(VideoProject, project_id)
        assert project is not None
        assert project.status == expected_status


def service_now() -> datetime:
    return datetime.now(UTC)


def test_matsca_keyframe_generator_returns_png_bytes() -> None:
    generator = MatscaKeyframeGenerator(provider=FakeMatscaProvider())

    assert generator("keyframe prompt") == b"png-bytes"


def test_matsca_keyframe_generator_downloads_url_result() -> None:
    generator = MatscaKeyframeGenerator(
        provider=FakeMatscaUrlProvider(),
        downloader=lambda url: f"downloaded:{url}".encode(),
    )

    assert generator("keyframe prompt") == b"downloaded:https://cdn.test/keyframe.png"


def test_matsca_keyframe_generator_creates_and_resumes_async_task() -> None:
    class AsyncProvider:
        def __init__(self):
            self.created = 0

        def create_generation_task(self, **kwargs: object) -> MatscaImageTask:
            self.created += 1
            assert kwargs["prompt"] == "keyframe prompt"
            return MatscaImageTask(id="task-keyframe", status="queued", images=[])

        def get_image_task(self, task_id: str) -> MatscaImageTask:
            assert task_id == "task-keyframe"
            return MatscaImageTask(
                id=task_id,
                status="completed",
                images=[GeneratedImage(content=b"async-png")],
            )

    provider = AsyncProvider()
    generator = MatscaKeyframeGenerator(
        provider=provider,
        poll_interval=0,
        poll_timeout=1,
    )
    created_ids: list[str] = []

    first = generator.generate(
        "keyframe prompt",
        task_id=None,
        on_task_created=created_ids.append,
    )
    resumed = generator.generate(
        "keyframe prompt",
        task_id="task-keyframe",
        on_task_created=lambda task_id: pytest.fail(task_id),
    )

    assert first == b"async-png"
    assert resumed == b"async-png"
    assert created_ids == ["task-keyframe"]
    assert provider.created == 1


def test_matsca_keyframe_generator_downloads_async_url_result() -> None:
    class AsyncUrlProvider:
        def create_generation_task(self, **kwargs: object) -> MatscaImageTask:
            del kwargs
            return MatscaImageTask(id="task-keyframe-url", status="queued", images=[])

        def get_image_task(self, task_id: str) -> MatscaImageTask:
            assert task_id == "task-keyframe-url"
            return MatscaImageTask(
                id=task_id,
                status="completed",
                images=[GeneratedImage(url="https://cdn.test/keyframe.png")],
            )

    generator = MatscaKeyframeGenerator(
        provider=AsyncUrlProvider(),
        downloader=lambda url: f"downloaded:{url}".encode(),
        poll_interval=0,
        poll_timeout=1,
    )

    content = generator.generate(
        "keyframe prompt",
        task_id=None,
        on_task_created=lambda task_id: None,
    )

    assert content == b"downloaded:https://cdn.test/keyframe.png"


def test_keyframe_generation_resumes_existing_direct_task_without_recreating(
    tmp_path: Path,
) -> None:
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

    class RecoverableGenerator:
        def __init__(self):
            self.task_ids: list[str | None] = []
            self.created = 0

        def generate(
            self,
            prompt: str,
            *,
            task_id: str | None,
            on_task_created,
        ) -> bytes:
            del prompt
            self.task_ids.append(task_id)
            if task_id is None:
                self.created += 1
                on_task_created("upstream-keyframe-1")
                raise TimeoutError("poll interrupted")
            return b"resumed"

    generator = RecoverableGenerator()

    with pytest.raises(TimeoutError):
        service.generate_keyframes(project_id, generator)

    with Session(service.engine) as session:
        pending = session.query(VideoKeyframe).one()
        assert pending.status == "pending"
        assert pending.upstream_task_id == "upstream-keyframe-1"

    service.generate_keyframes(project_id, generator)

    assert generator.created == 1
    assert generator.task_ids == [None, "upstream-keyframe-1"]
    with Session(service.engine) as session:
        completed = session.query(VideoKeyframe).one()
        assert completed.status == "completed"
        assert Path(completed.path).read_bytes() == b"resumed"


def test_keyframe_generation_persists_stable_client_task_id_before_submit(
    tmp_path: Path,
) -> None:
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

    class ClientTaskGenerator:
        def generate(self, prompt: str, **kwargs: object) -> bytes:
            del prompt
            assert kwargs["client_task_id"] == f"image-video-{project_id}-keyframe-0"
            kwargs["on_task_created"]("upstream-keyframe-client")  # type: ignore[operator]
            return b"keyframe"

    service.generate_keyframes(project_id, ClientTaskGenerator())

    with Session(service.engine) as session:
        keyframe = session.query(VideoKeyframe).one()
        assert keyframe.client_task_id == f"image-video-{project_id}-keyframe-0"
        assert keyframe.upstream_task_id == "upstream-keyframe-client"


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


def test_storyboard_request_includes_frame_settings_and_reference_annotations(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(
            title="demo",
            description="walk",
            start_frame=20,
            total_frames=60,
            fps=30,
            reference_images=[
                {"media_id": "ref-1", "label": "角色", "note": "红色外套"}
            ],
        )
    )
    planner = FakeStoryboardPlanner(
        StoryboardPlan(
            global_prompt="scene",
            character_lock="hero",
            scene_lock="street",
            camera_lock="wide",
            keyframes=[{"frame": 0, "description": "start", "prompt": "start"}],
            segments=[],
        )
    )

    service.generate_storyboard(project_id, planner)

    [request] = planner.calls
    assert request["start_frame"] == 20
    assert request["end_frame"] == 79
    assert request["total_frames"] == 60
    assert request["fps"] == 30
    assert request["references"] == [
        {"label": "角色", "note": "红色外套", "position": 0}
    ]


def test_storyboard_plan_requires_segments_to_match_keyframes(tmp_path: Path) -> None:
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
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start"},
                {"frame": 12, "description": "end", "prompt": "end"},
            ],
            segments=[{"start_frame": 0, "end_frame": 10, "motion": "walk"}],
        )
    )

    with pytest.raises(ValueError, match="片段边界必须对应关键帧"):
        service.generate_storyboard(project_id, planner)


def test_storyboard_plan_requires_contiguous_segments(tmp_path: Path) -> None:
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
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start"},
                {"frame": 12, "description": "middle", "prompt": "middle"},
                {"frame": 24, "description": "end", "prompt": "end"},
            ],
            segments=[
                {"start_frame": 0, "end_frame": 12, "motion": "walk"},
                {"start_frame": 0, "end_frame": 24, "motion": "turn"},
            ],
        )
    )

    with pytest.raises(ValueError, match="片段必须按关键帧连续衔接"):
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


def test_review_storyboard_saves_new_ai_version_without_confirming_it(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(
            title="demo",
            description="walk",
            total_frames=12,
            fps=24,
            reference_images=[],
        )
    )
    original_id = service.save_storyboard_version(
        project_id,
        source="user",
        plan=StoryboardPlan(
            global_prompt="original",
            character_lock="hero",
            scene_lock="street",
            camera_lock="wide",
            keyframes=[{"frame": 0, "description": "start", "prompt": "start"}],
            segments=[],
        ),
    )
    reviewer = FakeStoryboardReviewer(
        StoryboardPlan(
            global_prompt="reviewed",
            character_lock="hero",
            scene_lock="street",
            camera_lock="wide",
            keyframes=[{"frame": 0, "description": "start", "prompt": "improved"}],
            segments=[],
        )
    )

    reviewed_id = service.review_storyboard(
        project_id,
        version_id=original_id,
        reviewer=reviewer,
    )

    versions = service.list_storyboard_versions(project_id)
    assert reviewed_id != original_id
    assert versions[-1]["source"] == "ai"
    assert versions[-1]["suggestion"] == "DeepSeek 独立复审"
    assert versions[-1]["plan"]["global_prompt"] == "reviewed"
    assert reviewer.calls[0]["storyboard"]["global_prompt"] == "original"
    with Session(service.engine) as session:
        project = session.get(VideoProject, project_id)
        assert project is not None
        assert project.status == "awaiting_storyboard_approval"
        assert "approved_storyboard_version_id" not in project.settings


def test_generate_keyframes_persists_preview_pngs(tmp_path: Path) -> None:
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
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start prompt"},
                {"frame": 12, "description": "end", "prompt": "end prompt"},
            ],
            segments=[
                {
                    "start_frame": 0,
                    "end_frame": 12,
                    "motion": "walk forward",
                    "prompt": "smooth walk",
                }
            ],
        ),
    )
    service.confirm_storyboard(project_id, version_id)

    generated = service.generate_keyframes(
        project_id,
        generator=lambda prompt: b"\x89PNG\r\n\x1a\nfake",
    )

    assert [item["frame"] for item in generated] == [0, 12]
    assert all(str(item["path"]).endswith(".png") for item in generated)
    with Session(service.engine) as session:
        keyframes = session.query(VideoKeyframe).order_by(VideoKeyframe.frame).all()
        assert [keyframe.prompt for keyframe in keyframes] == [
            "start prompt",
            "end prompt",
        ]
        project = session.get(VideoProject, project_id)
        assert project is not None
        assert project.status == "awaiting_keyframe_approval"


def test_confirm_keyframes_moves_project_to_frame_generation(tmp_path: Path) -> None:
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
            keyframes=[{"frame": 0, "description": "start", "prompt": "start prompt"}],
            segments=[],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, generator=lambda prompt: prompt.encode())

    service.confirm_keyframes(project_id)

    with Session(service.engine) as session:
        project = session.get(VideoProject, project_id)
        assert project is not None
        assert project.status == "generating_frames"


def test_generate_intermediate_frames_runs_each_segment_in_frame_order(
    tmp_path: Path,
) -> None:
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
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start prompt"},
                {"frame": 3, "description": "middle", "prompt": "middle prompt"},
                {"frame": 6, "description": "end", "prompt": "end prompt"},
            ],
            segments=[
                {"start_frame": 0, "end_frame": 3, "motion": "walk", "prompt": "walk"},
                {"start_frame": 3, "end_frame": 6, "motion": "turn", "prompt": "turn"},
            ],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, generator=lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)
    generator = RecordingFrameGenerator()

    frames = service.generate_intermediate_frames(project_id, generator=generator)

    assert sorted(frame["frame"] for frame in frames) == [1, 2, 4, 5]
    calls = [call["frame"] for call in generator.calls]
    assert calls.index(1) < calls.index(2)
    assert calls.index(4) < calls.index(5)
    with Session(service.engine) as session:
        persisted = session.query(VideoFrame).order_by(VideoFrame.frame).all()
        assert [frame.frame for frame in persisted] == [1, 2, 4, 5]


def test_generate_intermediate_frames_persists_previous_frame_before_next(
    tmp_path: Path,
) -> None:
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
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start"},
                {"frame": 3, "description": "end", "prompt": "end"},
            ],
            segments=[{"start_frame": 0, "end_frame": 3, "motion": "walk"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, generator=lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)

    def generator(**kwargs: object) -> bytes:
        frame = int(kwargs["frame"])
        previous_path = Path(str(kwargs["previous_frame_path"]))
        if frame == 2:
            assert previous_path.is_file()
            assert previous_path.read_bytes() == b"frame-1"
        return f"frame-{frame}".encode()

    service.generate_intermediate_frames(project_id, generator=generator)


def test_intermediate_frame_resumes_existing_direct_task_without_recreating(
    tmp_path: Path,
) -> None:
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
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start"},
                {"frame": 2, "description": "end", "prompt": "end"},
            ],
            segments=[{"start_frame": 0, "end_frame": 2, "motion": "walk"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, generator=lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)

    class RecoverableFrameGenerator:
        def __init__(self):
            self.task_ids: list[str | None] = []
            self.created = 0

        def generate(self, **kwargs: object) -> bytes:
            task_id = kwargs["task_id"]
            assert task_id is None or isinstance(task_id, str)
            self.task_ids.append(task_id)
            if task_id is None:
                self.created += 1
                kwargs["on_task_created"]("upstream-frame-1")  # type: ignore[operator]
                raise TimeoutError("poll interrupted")
            return b"resumed-frame"

    generator = RecoverableFrameGenerator()

    with pytest.raises(TimeoutError):
        service.generate_intermediate_frames(project_id, generator=generator)

    with Session(service.engine) as session:
        pending = session.query(VideoFrame).one()
        assert pending.upstream_task_id == "upstream-frame-1"

    service.generate_intermediate_frames(project_id, generator=generator)

    assert generator.created == 1
    assert generator.task_ids == [None, "upstream-frame-1"]
    with Session(service.engine) as session:
        completed = session.query(VideoFrame).one()
        assert completed.status == "completed"
        assert Path(completed.path).read_bytes() == b"resumed-frame"


def test_intermediate_frame_persists_stable_client_task_id_before_submit(
    tmp_path: Path,
) -> None:
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
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start"},
                {"frame": 2, "description": "end", "prompt": "end"},
            ],
            segments=[{"start_frame": 0, "end_frame": 2, "motion": "walk"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, generator=lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)

    class ClientTaskGenerator:
        def generate(self, **kwargs: object) -> bytes:
            assert kwargs["client_task_id"] == f"image-video-{project_id}-frame-1"
            kwargs["on_task_created"]("upstream-frame-client")  # type: ignore[operator]
            return b"frame"

    service.generate_intermediate_frames(project_id, generator=ClientTaskGenerator())

    with Session(service.engine) as session:
        frame = session.query(VideoFrame).one()
        assert frame.client_task_id == f"image-video-{project_id}-frame-1"
        assert frame.upstream_task_id == "upstream-frame-client"


def test_intermediate_frame_with_result_url_redownloads_without_generator(
    tmp_path: Path,
) -> None:
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
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start"},
                {"frame": 2, "description": "end", "prompt": "end"},
            ],
            segments=[{"start_frame": 0, "end_frame": 2, "motion": "walk"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, generator=lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)
    with Session(service.engine) as session:
        session.add(
            VideoFrame(
                id="frame-url",
                project_id=project_id,
                frame=1,
                segment_start_frame=0,
                segment_end_frame=2,
                prompt="walk",
                path=(
                    tmp_path
                    / "data"
                    / "video_projects"
                    / project_id
                    / "frames"
                    / "frame_000001.png"
                ).as_posix(),
                status="needs_attention",
                error_message="图片下载失败",
                upstream_task_id="task-frame-url",
                client_task_id=f"image-video-{project_id}-frame-1",
                result_url="https://cdn.test/frame.png",
                created_at=service_now(),
                updated_at=service_now(),
            )
        )
        session.commit()

    class ShouldNotGenerate:
        def generate(self, **kwargs: object) -> bytes:
            del kwargs
            raise AssertionError("已有 result_url 时不应重新生成")

    result = service.generate_intermediate_frames(
        project_id,
        generator=ShouldNotGenerate(),
        downloader=lambda url: b"redownloaded",
    )

    assert result[0]["status"] == "completed"
    with Session(service.engine) as session:
        frame = session.query(VideoFrame).one()
        assert frame.result_url == "https://cdn.test/frame.png"
        assert Path(frame.path).read_bytes() == b"redownloaded"


def test_generate_intermediate_frames_skips_existing_completed_frames(
    tmp_path: Path,
) -> None:
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
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start"},
                {"frame": 3, "description": "end", "prompt": "end"},
            ],
            segments=[{"start_frame": 0, "end_frame": 3, "motion": "walk"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, generator=lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)
    first_generator = RecordingFrameGenerator()
    service.generate_intermediate_frames(project_id, generator=first_generator)
    second_generator = RecordingFrameGenerator()

    generated = service.generate_intermediate_frames(
        project_id, generator=second_generator
    )

    assert generated == []
    assert second_generator.calls == []
    with Session(service.engine) as session:
        assert session.query(VideoFrame).count() == 2


def test_generate_intermediate_frame_timeout_marks_needs_attention(
    tmp_path: Path,
) -> None:
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
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start"},
                {"frame": 2, "description": "end", "prompt": "end"},
            ],
            segments=[{"start_frame": 0, "end_frame": 2, "motion": "walk"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, generator=lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)

    with pytest.raises(TimeoutError):
        service.generate_intermediate_frames(
            project_id,
            generator=lambda **kwargs: (_ for _ in ()).throw(
                TimeoutError("uncertain")
            ),
        )

    with Session(service.engine) as session:
        project = session.get(VideoProject, project_id)
        frame = session.query(VideoFrame).filter_by(frame=1).one()
        assert project is not None
        assert project.status == "needs_attention"
        assert frame.status == "needs_attention"
        assert frame.error_message == "上游请求超时，结果状态不确定"


def test_generate_intermediate_frames_interleaves_segments_by_offset(
    tmp_path: Path,
) -> None:
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
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start prompt"},
                {"frame": 3, "description": "middle", "prompt": "middle prompt"},
                {"frame": 6, "description": "end", "prompt": "end prompt"},
            ],
            segments=[
                {"start_frame": 0, "end_frame": 3, "motion": "walk"},
                {"start_frame": 3, "end_frame": 6, "motion": "turn"},
            ],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, generator=lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)
    generator = RecordingFrameGenerator()

    service.generate_intermediate_frames(project_id, generator=generator)

    calls = [call["frame"] for call in generator.calls]
    assert calls.index(1) < calls.index(2)
    assert calls.index(4) < calls.index(5)


def test_generate_intermediate_frames_runs_segments_in_parallel(
    tmp_path: Path,
) -> None:
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
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start"},
                {"frame": 3, "description": "middle", "prompt": "middle"},
                {"frame": 6, "description": "end", "prompt": "end"},
            ],
            segments=[
                {"start_frame": 0, "end_frame": 3, "motion": "walk"},
                {"start_frame": 3, "end_frame": 6, "motion": "turn"},
            ],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, generator=lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)
    first_offset_barrier = threading.Barrier(2)
    entered_first_offset: list[int] = []
    lock = threading.Lock()

    def generator(**kwargs: object) -> bytes:
        frame = int(kwargs["frame"])
        if frame in {1, 4}:
            with lock:
                entered_first_offset.append(frame)
            first_offset_barrier.wait(timeout=2)
        return f"frame-{frame}".encode()

    service.generate_intermediate_frames(project_id, generator=generator)

    assert sorted(entered_first_offset) == [1, 4]


def test_intermediate_frame_reference_selection_limits_user_references(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(
            title="demo",
            description="walk",
            reference_images=[
                {"media_id": f"ref-{index}", "label": "角色"} for index in range(8)
            ],
        )
    )
    version_id = service.save_storyboard_version(
        project_id,
        source="user",
        plan=StoryboardPlan(
            global_prompt="scene",
            character_lock="hero",
            scene_lock="street",
            camera_lock="wide",
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start prompt"},
                {"frame": 3, "description": "end", "prompt": "end prompt"},
            ],
            segments=[{"start_frame": 0, "end_frame": 3, "motion": "walk"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, generator=lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)
    generator = RecordingFrameGenerator()

    service.generate_intermediate_frames(project_id, generator=generator)

    assert generator.calls[0]["references"] == [f"ref-{index}" for index in range(7)]
    assert generator.calls[0]["previous_frame_path"] is not None
    assert generator.calls[1]["references"] == [f"ref-{index}" for index in range(6)]
    assert generator.calls[1]["previous_frame_path"] == (
        service.data_root / "video_projects" / project_id / "frames" / "frame_000001.png"
    ).as_posix()


def test_regenerate_missing_or_invalid_frame_and_timeout_needs_attention(
    tmp_path: Path,
) -> None:
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
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start prompt"},
                {"frame": 3, "description": "end", "prompt": "end prompt"},
            ],
            segments=[{"start_frame": 0, "end_frame": 3, "motion": "walk"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, generator=lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)
    service.generate_intermediate_frames(
        project_id, generator=lambda **kwargs: f"frame-{kwargs['frame']}".encode()
    )
    with Session(service.engine) as session:
        frame = session.query(VideoFrame).filter_by(frame=2).one()
        frame.status = "invalid"
        Path(frame.path).unlink()
        session.commit()

    repaired = service.repair_frame(
        project_id,
        frame=2,
        generator=lambda **kwargs: b"repaired",
    )

    assert repaired["status"] == "completed"
    assert Path(str(repaired["path"])).read_bytes() == b"repaired"

    timed_out = service.repair_frame(
        project_id,
        frame=2,
        generator=lambda **kwargs: (_ for _ in ()).throw(TimeoutError("upstream")),
    )

    assert timed_out["status"] == "needs_attention"
    with Session(service.engine) as session:
        frame = session.query(VideoFrame).filter_by(frame=2).one()
        assert frame.status == "needs_attention"
        assert "upstream" in frame.error_message


def test_list_frame_issues_reports_missing_records_and_files(tmp_path: Path) -> None:
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
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start prompt"},
                {"frame": 3, "description": "end", "prompt": "end prompt"},
            ],
            segments=[{"start_frame": 0, "end_frame": 3, "motion": "walk"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, generator=lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)
    service.generate_intermediate_frames(
        project_id, generator=lambda **kwargs: f"frame-{kwargs['frame']}".encode()
    )
    with Session(service.engine) as session:
        frame = session.query(VideoFrame).filter_by(frame=2).one()
        Path(frame.path).unlink()
        session.delete(session.query(VideoFrame).filter_by(frame=1).one())
        session.commit()

    issues = service.list_frame_issues(project_id)

    assert issues == [
        {
            "frame": 1,
            "time_seconds": 1 / 24,
            "status": "missing_record",
            "segment_start_frame": 0,
            "segment_end_frame": 3,
            "prompt": "walk",
            "error_message": "",
        },
        {
            "frame": 2,
            "time_seconds": 2 / 24,
            "status": "missing_file",
            "segment_start_frame": 0,
            "segment_end_frame": 3,
            "prompt": "walk",
            "error_message": "",
        },
    ]


def test_frame_issues_include_error_and_time_for_frontend(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(
            title="demo",
            description="walk",
            total_frames=10,
            fps=10,
            reference_images=[],
        )
    )
    version_id = service.save_storyboard_version(
        project_id,
        source="user",
        plan=StoryboardPlan(
            global_prompt="scene",
            character_lock="hero",
            scene_lock="street",
            camera_lock="wide",
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start"},
                {"frame": 9, "description": "end", "prompt": "end"},
            ],
            segments=[{"start_frame": 0, "end_frame": 9, "motion": "turn slowly"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, generator=lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)
    with Session(service.engine) as session:
        session.add(
            VideoFrame(
                id="frame-3",
                project_id=project_id,
                frame=3,
                segment_start_frame=0,
                segment_end_frame=9,
                prompt="turn slowly",
                path=(tmp_path / "missing.png").as_posix(),
                status="failed",
                error_message="Matsca HTTP 400",
                created_at=service_now(),
                updated_at=service_now(),
            )
        )
        session.commit()

    issues = service.list_frame_issues(project_id)

    failed = next(issue for issue in issues if issue["frame"] == 3)
    assert failed == {
        "frame": 3,
        "time_seconds": 0.3,
        "status": "failed",
        "segment_start_frame": 0,
        "segment_end_frame": 9,
        "prompt": "turn slowly",
        "error_message": "Matsca HTTP 400",
    }
    missing = next(issue for issue in issues if issue["frame"] == 1)
    assert missing["time_seconds"] == 0.1
    assert missing["prompt"] == "turn slowly"
    assert missing["error_message"] == ""


def test_repair_frame_creates_missing_record_from_storyboard_segment(
    tmp_path: Path,
) -> None:
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
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start prompt"},
                {"frame": 3, "description": "end", "prompt": "end prompt"},
            ],
            segments=[{"start_frame": 0, "end_frame": 3, "motion": "walk", "prompt": "smooth"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, generator=lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)

    repaired = service.repair_frame(
        project_id,
        frame=1,
        generator=lambda **kwargs: b"repaired",
    )

    assert repaired["status"] == "completed"
    assert repaired["frame"] == 1
    with Session(service.engine) as session:
        frame = session.query(VideoFrame).filter_by(frame=1).one()
        assert frame.segment_start_frame == 0
        assert frame.segment_end_frame == 3
        assert frame.prompt == "walk"
        assert Path(frame.path).read_bytes() == b"repaired"


def test_repair_frame_resumes_existing_direct_task_without_recreating(
    tmp_path: Path,
) -> None:
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
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start"},
                {"frame": 2, "description": "end", "prompt": "end"},
            ],
            segments=[{"start_frame": 0, "end_frame": 2, "motion": "walk"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, generator=lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)

    class RecoverableRepairGenerator:
        def __init__(self):
            self.created = 0
            self.task_ids: list[str | None] = []

        def generate(self, **kwargs: object) -> bytes:
            task_id = kwargs["task_id"]
            assert task_id is None or isinstance(task_id, str)
            self.task_ids.append(task_id)
            if task_id is None:
                self.created += 1
                kwargs["on_task_created"]("upstream-repair-1")  # type: ignore[operator]
                raise TimeoutError("poll interrupted")
            return b"repaired-from-existing-task"

    generator = RecoverableRepairGenerator()

    first = service.repair_frame(project_id, frame=1, generator=generator)
    second = service.repair_frame(project_id, frame=1, generator=generator)

    assert first["status"] == "needs_attention"
    assert second["status"] == "completed"
    assert generator.created == 1
    assert generator.task_ids == [None, "upstream-repair-1"]
    with Session(service.engine) as session:
        frame = session.query(VideoFrame).one()
        assert frame.upstream_task_id == "upstream-repair-1"
        assert Path(frame.path).read_bytes() == b"repaired-from-existing-task"


def test_stitch_video_requires_no_missing_frames_and_outputs_silent_h264_mp4(
    tmp_path: Path,
) -> None:
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
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start prompt"},
                {"frame": 3, "description": "end", "prompt": "end prompt"},
            ],
            segments=[{"start_frame": 0, "end_frame": 3, "motion": "walk"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, generator=lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)
    service.generate_intermediate_frames(
        project_id, generator=lambda **kwargs: f"frame-{kwargs['frame']}".encode()
    )
    runner = RecordingFfmpegRunner()

    result = service.stitch_video(
        project_id,
        ffmpeg_path=r"D:\ffmpeg\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe",
        runner=runner,
    )

    assert result["status"] == "completed"
    assert str(result["path"]).endswith(".mp4")
    command = runner.commands[0]
    assert "-an" in command
    assert command[command.index("-c:v") : command.index("-c:v") + 2] == [
        "-c:v",
        "libx264",
    ]
    assert command[command.index("-pix_fmt") : command.index("-pix_fmt") + 2] == [
        "-pix_fmt",
        "yuv420p",
    ]
    with Session(service.engine) as session:
        project = session.get(VideoProject, project_id)
        assert project is not None
        assert project.status == "completed"
        assert str(project.settings["output_video_path"]).endswith(".mp4")


@pytest.mark.parametrize("missing_kind", ["record", "file"])
def test_stitch_video_rejects_incomplete_frame_sequence(
    tmp_path: Path,
    missing_kind: str,
) -> None:
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
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start"},
                {"frame": 3, "description": "end", "prompt": "end"},
            ],
            segments=[{"start_frame": 0, "end_frame": 3, "motion": "walk"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, generator=lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)
    if missing_kind == "file":
        service.generate_intermediate_frames(
            project_id, generator=lambda **kwargs: f"frame-{kwargs['frame']}".encode()
        )
        with Session(service.engine) as session:
            frame = session.query(VideoFrame).filter_by(frame=1).one()
            Path(frame.path).unlink()

    runner = RecordingFfmpegRunner()
    with pytest.raises(ValueError, match="缺失"):
        service.stitch_video(
            project_id,
            ffmpeg_path="ffmpeg.exe",
            runner=runner,
        )

    assert runner.commands == []
    with Session(service.engine) as session:
        project = session.get(VideoProject, project_id)
        assert project is not None
        assert project.status != "completed"


def test_frame_numbering_supports_more_than_999(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(title="demo", description="long", reference_images=[])
    )
    version_id = service.save_storyboard_version(
        project_id,
        source="user",
        plan=StoryboardPlan(
            global_prompt="scene",
            character_lock="hero",
            scene_lock="street",
            camera_lock="wide",
            keyframes=[
                {"frame": 0, "description": "opening", "prompt": "opening prompt"},
                {"frame": 1002, "description": "end", "prompt": "end prompt"},
            ],
            segments=[{"start_frame": 0, "end_frame": 1002, "motion": "walk"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, generator=lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)
    frame_path = Path("data") / "video_projects" / project_id / "frames" / "frame_001001.png"
    frame_path.parent.mkdir(parents=True, exist_ok=True)
    with Session(service.engine) as session:
        session.add(
            VideoFrame(
                id="frame-1001",
                project_id=project_id,
                frame=1001,
                segment_start_frame=0,
                segment_end_frame=1002,
                prompt="walk",
                path=frame_path.as_posix(),
                status="invalid",
                error_message="",
                created_at=service_now(),
                updated_at=service_now(),
            )
        )
        session.commit()

    repaired = service.repair_frame(
        project_id, frame=1001, generator=lambda **kwargs: b"frame-1001"
    )

    assert repaired["frame"] == 1001
    assert str(repaired["path"]).endswith("frame_001001.png")


def test_regenerate_selected_keyframe_replaces_only_that_preview(tmp_path: Path) -> None:
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
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start prompt"},
                {"frame": 12, "description": "end", "prompt": "end prompt"},
            ],
            segments=[],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, generator=lambda prompt: prompt.encode())

    regenerated = service.regenerate_keyframe(
        project_id,
        frame=12,
        generator=lambda prompt: f"new {prompt}".encode(),
    )
    previews = service.list_keyframes(project_id)

    assert regenerated["frame"] == 12
    assert [preview["frame"] for preview in previews] == [0, 12]
    with Session(service.engine) as session:
        unchanged = session.query(VideoKeyframe).filter_by(frame=0).one()
        changed = session.query(VideoKeyframe).filter_by(frame=12).one()
        assert Path(unchanged.path).read_bytes() == b"start prompt"
        assert Path(changed.path).read_bytes() == b"new end prompt"


def test_keyframe_previews_include_review_fields_for_frontend(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(
            title="demo",
            description="walk",
            total_frames=10,
            fps=10,
            reference_images=[],
        )
    )
    version_id = service.save_storyboard_version(
        project_id,
        source="user",
        plan=StoryboardPlan(
            global_prompt="scene",
            character_lock="hero",
            scene_lock="street",
            camera_lock="wide",
            keyframes=[
                {"frame": 0, "description": "start desc", "prompt": "start prompt"},
                {"frame": 9, "description": "end desc", "prompt": "end prompt"},
            ],
            segments=[{"start_frame": 0, "end_frame": 9, "motion": "turn"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, generator=lambda prompt: prompt.encode())

    previews = service.list_keyframes(project_id)

    assert previews[0] == {
        "keyframe_id": previews[0]["keyframe_id"],
        "frame": 0,
        "time_seconds": 0.0,
        "description": "start desc",
        "prompt": "start prompt",
        "path": previews[0]["path"],
        "media_url": f"/api/v1/video-projects/{project_id}/keyframes/0/media",
        "status": "completed",
    }
    assert previews[1]["time_seconds"] == 0.9
    assert previews[1]["description"] == "end desc"
    assert previews[1]["prompt"] == "end prompt"


def test_regenerate_keyframe_invalidates_only_adjacent_segments(tmp_path: Path) -> None:
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
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start prompt"},
                {"frame": 12, "description": "middle", "prompt": "middle prompt"},
                {"frame": 24, "description": "end", "prompt": "end prompt"},
                {"frame": 36, "description": "stop", "prompt": "stop prompt"},
            ],
            segments=[
                {"start_frame": 0, "end_frame": 12, "motion": "walk"},
                {"start_frame": 12, "end_frame": 24, "motion": "turn"},
                {"start_frame": 24, "end_frame": 36, "motion": "stop"},
            ],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, generator=lambda prompt: prompt.encode())
    with Session(service.engine) as session:
        project = session.get(VideoProject, project_id)
        assert project is not None
        project.settings = {
            **project.settings,
            "output_video_path": (tmp_path / "old.mp4").as_posix(),
        }
        for frame, start, end in [(1, 0, 12), (13, 12, 24), (25, 24, 36)]:
            session.add(
                VideoFrame(
                    id=f"frame-{frame}",
                    project_id=project_id,
                    frame=frame,
                    segment_start_frame=start,
                    segment_end_frame=end,
                    prompt="existing",
                    path=(tmp_path / f"frame-{frame}.png").as_posix(),
                    status="completed",
                    error_message="",
                    created_at=service_now(),
                    updated_at=service_now(),
                )
            )
        session.commit()

    regenerated = service.regenerate_keyframe(
        project_id,
        frame=12,
        generator=lambda prompt: prompt.encode(),
    )

    assert regenerated["invalidated_segments"] == [
        {"start_frame": 0, "end_frame": 12},
        {"start_frame": 12, "end_frame": 24},
    ]
    with Session(service.engine) as session:
        project = session.get(VideoProject, project_id)
        assert project is not None
        assert project.settings["invalidated_segments"] == [
            {"start_frame": 0, "end_frame": 12},
            {"start_frame": 12, "end_frame": 24},
        ]
        assert "output_video_path" not in project.settings
        assert project.status == "awaiting_keyframe_approval"
        frames = session.query(VideoFrame).order_by(VideoFrame.frame).all()
        assert [(item.frame, item.status) for item in frames] == [
            (1, "invalid"),
            (13, "invalid"),
            (25, "completed"),
        ]


def test_regenerate_keyframe_resumes_existing_direct_task_without_recreating(
    tmp_path: Path,
) -> None:
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
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start"},
                {"frame": 12, "description": "end", "prompt": "end"},
            ],
            segments=[{"start_frame": 0, "end_frame": 12, "motion": "walk"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, lambda prompt: prompt.encode())
    service.request_keyframe_regeneration(
        project_id,
        frame=12,
        enqueue=lambda: "job-regenerate",
    )

    class RecoverableGenerator:
        def __init__(self):
            self.created = 0
            self.task_ids: list[str | None] = []

        def generate(
            self,
            prompt: str,
            *,
            task_id: str | None,
            on_task_created,
        ) -> bytes:
            del prompt
            self.task_ids.append(task_id)
            if task_id is None:
                self.created += 1
                on_task_created("upstream-regenerate-1")
                raise TimeoutError("poll interrupted")
            return b"regenerated"

    generator = RecoverableGenerator()

    with pytest.raises(TimeoutError):
        service.regenerate_keyframe(project_id, frame=12, generator=generator)
    service.regenerate_keyframe(project_id, frame=12, generator=generator)

    assert generator.created == 1
    assert generator.task_ids == [None, "upstream-regenerate-1"]
    with Session(service.engine) as session:
        keyframe = session.query(VideoKeyframe).filter_by(frame=12).one()
        assert keyframe.upstream_task_id == "upstream-regenerate-1"
        assert keyframe.status == "completed"
        assert Path(keyframe.path).read_bytes() == b"regenerated"
