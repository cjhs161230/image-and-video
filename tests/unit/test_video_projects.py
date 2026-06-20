from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
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
from image_video.infrastructure.providers.matsca import GeneratedImage


class FakeStoryboardPlanner:
    def __init__(self, plan: StoryboardPlan):
        self.plan = plan
        self.calls: list[Mapping[str, object]] = []

    def create_storyboard(self, request: Mapping[str, object]) -> StoryboardPlan:
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
    return VideoProjectService(engine, data_root=tmp_path / "data")


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
        def create_storyboard(self, request: Mapping[str, object]) -> StoryboardPlan:
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

    assert [frame["frame"] for frame in frames] == [1, 4, 2, 5]
    assert [call["frame"] for call in generator.calls] == [1, 4, 2, 5]
    with Session(service.engine) as session:
        persisted = session.query(VideoFrame).order_by(VideoFrame.frame).all()
        assert [frame.frame for frame in persisted] == [1, 2, 4, 5]


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

    assert [call["frame"] for call in generator.calls] == [1, 4, 2, 5]


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
