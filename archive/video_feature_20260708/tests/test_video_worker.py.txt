from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from image_video.application.video_projects import (
    VideoProjectDraftRequest,
    VideoProjectService,
)
from image_video.domain.jobs import JobStatus
from image_video.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from image_video.infrastructure.database.models import (
    Job,
    VideoFrame,
    VideoKeyframe,
    VideoProject,
    VideoStoryboardVersion,
)
from image_video.infrastructure.database.queue import JobQueue
from image_video.infrastructure.providers.deepseek import StoryboardPlan
from image_video.worker.runner import WorkerRunner
from image_video.worker.video_handler import (
    VideoFrameHandler,
    VideoFrameRepairHandler,
    VideoKeyframeHandler,
    VideoKeyframeRegenerateHandler,
    VideoStitchHandler,
    VideoStoryboardHandler,
    VideoStoryboardReviewHandler,
)


class RecordingPlanner:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    def create_storyboard(self, request: dict[str, object]) -> StoryboardPlan:
        self.calls.append(request)
        return StoryboardPlan(
            global_prompt="same scene",
            character_lock="hero",
            scene_lock="street",
            camera_lock="wide",
            keyframes=[
                {"frame": 0, "description": "start", "prompt": "start"},
                {"frame": 12, "description": "end", "prompt": "end"},
            ],
            segments=[{"start_frame": 0, "end_frame": 12, "motion": "turn"}],
        )


class RecordingReviewer:
    def review_storyboard(self, request: dict[str, object]) -> StoryboardPlan:
        return StoryboardPlan(
            global_prompt=f"reviewed {request['storyboard']['global_prompt']}",
            character_lock="hero",
            scene_lock="street",
            camera_lock="wide",
            keyframes=[{"frame": 0, "description": "start", "prompt": "improved"}],
            segments=[],
        )


def make_service_and_queue(tmp_path: Path) -> tuple[VideoProjectService, JobQueue]:
    engine = create_database_engine(tmp_path / "video-worker.db")
    initialize_database(engine)
    return (
        VideoProjectService(
            engine,
            data_root=tmp_path / "data",
            validate_image_saves=False,
        ),
        JobQueue(engine),
    )


def test_video_storyboard_worker_generates_version_and_gate_status(
    tmp_path: Path,
) -> None:
    service, queue = make_service_and_queue(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(title="demo", description="turn", reference_images=[])
    )
    job_id = queue.enqueue("video.storyboard.generate", {"project_id": project_id})
    planner = RecordingPlanner()
    runner = WorkerRunner(
        queue=queue,
        handlers={
            "video.storyboard.generate": VideoStoryboardHandler(
                service=service,
                planner=planner,
                queue=queue,
            )
        },
        worker_id="video-worker",
    )

    assert runner.run_once()

    assert queue.get(job_id).status == JobStatus.COMPLETED
    assert planner.calls[0]["description"] == "turn"
    with Session(service.engine) as session:
        project = session.get(VideoProject, project_id)
        versions = session.query(VideoStoryboardVersion).all()
        assert project is not None
        assert project.status == "awaiting_storyboard_approval"
        assert len(versions) == 1
        assert versions[0].project_id == project_id


def test_video_storyboard_review_worker_saves_unconfirmed_ai_version(
    tmp_path: Path,
) -> None:
    service, queue = make_service_and_queue(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(title="demo", description="turn", reference_images=[])
    )
    version_id = service.save_storyboard_version(
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
    job_id = service.request_storyboard_review(
        project_id,
        version_id=version_id,
        enqueue=lambda: queue.enqueue(
            "video.storyboard.review",
            {"project_id": project_id, "version_id": version_id},
        ),
    )
    runner = WorkerRunner(
        queue=queue,
        handlers={
            "video.storyboard.review": VideoStoryboardReviewHandler(
                service=service,
                reviewer=RecordingReviewer(),
                queue=queue,
            )
        },
        worker_id="video-worker",
    )

    assert runner.run_once()

    assert queue.get(job_id).status == JobStatus.COMPLETED
    versions = service.list_storyboard_versions(project_id)
    assert len(versions) == 2
    assert versions[-1]["source"] == "ai"
    assert versions[-1]["suggestion"] == "DeepSeek 独立复审"
    with Session(service.engine) as session:
        project = session.get(VideoProject, project_id)
        assert project is not None
        assert project.status == "awaiting_storyboard_approval"
        assert "approved_storyboard_version_id" not in project.settings


def test_video_storyboard_worker_does_not_persist_version_after_cancel(
    tmp_path: Path,
) -> None:
    service, queue = make_service_and_queue(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(title="demo", description="turn", reference_images=[])
    )
    job_id = queue.enqueue("video.storyboard.generate", {"project_id": project_id})

    class CancellingPlanner:
        def create_storyboard(self, request: dict[str, object]) -> StoryboardPlan:
            del request
            queue.cancel(job_id)
            return StoryboardPlan(
                global_prompt="same scene",
                character_lock="hero",
                scene_lock="street",
                camera_lock="wide",
                keyframes=[
                    {"frame": 0, "description": "start", "prompt": "start"},
                    {"frame": 12, "description": "end", "prompt": "end"},
                ],
                segments=[{"start_frame": 0, "end_frame": 12, "motion": "turn"}],
            )

    runner = WorkerRunner(
        queue=queue,
        handlers={
            "video.storyboard.generate": VideoStoryboardHandler(
                service=service,
                planner=CancellingPlanner(),
                queue=queue,
            )
        },
        worker_id="video-worker",
    )

    assert runner.run_once()

    assert queue.get(job_id).status == JobStatus.CANCELLED
    with Session(service.engine) as session:
        project = session.get(VideoProject, project_id)
        assert project is not None
        assert project.status == "planning"
        assert session.query(VideoStoryboardVersion).count() == 0


def test_video_keyframe_worker_generates_previews_and_gate_status(
    tmp_path: Path,
) -> None:
    service, queue = make_service_and_queue(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(title="demo", description="turn", reference_images=[])
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
            segments=[{"start_frame": 0, "end_frame": 12, "motion": "turn"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    job_id = queue.enqueue("video.keyframes.generate", {"project_id": project_id})
    prompts: list[str] = []
    runner = WorkerRunner(
        queue=queue,
        handlers={
            "video.keyframes.generate": VideoKeyframeHandler(
                service=service,
                generator=lambda prompt: prompts.append(prompt) or prompt.encode(),
            )
        },
        worker_id="video-worker",
    )

    assert runner.run_once()

    assert queue.get(job_id).status == JobStatus.COMPLETED
    assert prompts == ["start", "end"]
    with Session(service.engine) as session:
        project = session.get(VideoProject, project_id)
        keyframes = session.query(VideoKeyframe).order_by(VideoKeyframe.frame).all()
        assert project is not None
        assert project.status == "awaiting_keyframe_approval"
        assert [keyframe.frame for keyframe in keyframes] == [0, 12]


def test_video_keyframe_worker_stops_without_persisting_after_cancel(
    tmp_path: Path,
) -> None:
    service, queue = make_service_and_queue(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(title="demo", description="turn", reference_images=[])
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
            segments=[{"start_frame": 0, "end_frame": 12, "motion": "turn"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    job_id = queue.enqueue("video.keyframes.generate", {"project_id": project_id})

    def cancel_after_first_result(prompt: str) -> bytes:
        queue.cancel(job_id)
        return prompt.encode()

    runner = WorkerRunner(
        queue=queue,
        handlers={
            "video.keyframes.generate": VideoKeyframeHandler(
                service=service,
                generator=cancel_after_first_result,
                queue=queue,
            )
        },
        worker_id="video-worker",
    )

    assert runner.run_once()

    assert queue.get(job_id).status == JobStatus.CANCELLED
    with Session(service.engine) as session:
        project = session.get(VideoProject, project_id)
        assert project is not None
        assert project.status == "generating_keyframes"
        assert session.query(VideoKeyframe).count() == 0


def test_video_keyframe_regenerate_worker_regenerates_selected_keyframe(
    tmp_path: Path,
) -> None:
    service, queue = make_service_and_queue(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(title="demo", description="turn", reference_images=[])
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
            segments=[{"start_frame": 0, "end_frame": 12, "motion": "turn"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, lambda prompt: prompt.encode())
    job_id = queue.enqueue(
        "video.keyframe.regenerate",
        {"project_id": project_id, "frame": 12},
    )
    prompts: list[str] = []
    runner = WorkerRunner(
        queue=queue,
        handlers={
            "video.keyframe.regenerate": VideoKeyframeRegenerateHandler(
                service=service,
                generator=lambda prompt: prompts.append(prompt) or b"regenerated",
            )
        },
        worker_id="video-worker",
    )

    assert runner.run_once()

    assert queue.get(job_id).status == JobStatus.COMPLETED
    assert prompts == ["end"]
    with Session(service.engine) as session:
        keyframe = session.query(VideoKeyframe).filter_by(frame=12).one()
        project = session.get(VideoProject, project_id)
        assert Path(keyframe.path).read_bytes() == b"regenerated"
        assert project is not None
        assert project.settings["invalidated_segments"] == [
            {"start_frame": 0, "end_frame": 12}
        ]


def test_video_keyframe_regenerate_worker_does_not_overwrite_after_cancel(
    tmp_path: Path,
) -> None:
    service, queue = make_service_and_queue(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(title="demo", description="turn", reference_images=[])
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
            segments=[{"start_frame": 0, "end_frame": 12, "motion": "turn"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, lambda prompt: prompt.encode())
    original_path = service.list_keyframes(project_id)[1]["path"]
    job_id = queue.enqueue(
        "video.keyframe.regenerate",
        {"project_id": project_id, "frame": 12},
    )

    def cancel_after_result(prompt: str) -> bytes:
        del prompt
        queue.cancel(job_id)
        return b"replacement"

    runner = WorkerRunner(
        queue=queue,
        handlers={
            "video.keyframe.regenerate": VideoKeyframeRegenerateHandler(
                service=service,
                generator=cancel_after_result,
                queue=queue,
            )
        },
        worker_id="video-worker",
    )

    assert runner.run_once()

    assert queue.get(job_id).status == JobStatus.CANCELLED
    assert Path(str(original_path)).read_bytes() == b"end"
    with Session(service.engine) as session:
        project = session.get(VideoProject, project_id)
        assert project is not None
        assert "invalidated_segments" not in project.settings


def test_video_frame_worker_generates_intermediate_frames(
    tmp_path: Path,
) -> None:
    service, queue = make_service_and_queue(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(title="demo", description="turn", reference_images=[])
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
            segments=[{"start_frame": 0, "end_frame": 3, "motion": "turn"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)
    job_id = queue.enqueue("video.frames.generate", {"project_id": project_id})
    frames_seen: list[int] = []
    runner = WorkerRunner(
        queue=queue,
        handlers={
            "video.frames.generate": VideoFrameHandler(
                service=service,
                generator=lambda **kwargs: frames_seen.append(kwargs["frame"])
                or f"frame-{kwargs['frame']}".encode(),
            )
        },
        worker_id="video-worker",
    )

    assert runner.run_once()

    assert queue.get(job_id).status == JobStatus.COMPLETED
    assert frames_seen == [1, 2]
    with Session(service.engine) as session:
        project = session.get(VideoProject, project_id)
        frames = session.query(VideoFrame).order_by(VideoFrame.frame).all()
        assert project is not None
        assert project.status == "generating_frames"
        assert [frame.frame for frame in frames] == [1, 2]


def test_video_frame_worker_enqueues_stitch_when_frames_complete(
    tmp_path: Path,
) -> None:
    service, queue = make_service_and_queue(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(title="demo", description="turn", reference_images=[])
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
            segments=[{"start_frame": 0, "end_frame": 2, "motion": "turn"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)
    queue.enqueue("video.frames.generate", {"project_id": project_id})
    runner = WorkerRunner(
        queue=queue,
        handlers={
            "video.frames.generate": VideoFrameHandler(
                service=service,
                generator=lambda **kwargs: f"frame-{kwargs['frame']}".encode(),
                queue=queue,
                ffmpeg_path="ffmpeg.exe",
            )
        },
        worker_id="video-worker",
    )

    assert runner.run_once()

    with Session(service.engine) as session:
        stitch_job = session.query(Job).filter_by(kind="video.stitch").one()
        assert stitch_job.payload == {
            "project_id": project_id,
            "ffmpeg_path": "ffmpeg.exe",
        }


def test_video_frame_worker_does_not_enqueue_duplicate_active_stitch(
    tmp_path: Path,
) -> None:
    service, queue = make_service_and_queue(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(title="demo", description="turn", reference_images=[])
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
            segments=[{"start_frame": 0, "end_frame": 2, "motion": "turn"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)
    queue.enqueue("video.frames.generate", {"project_id": project_id})
    queue.enqueue(
        "video.stitch",
        {"project_id": project_id, "ffmpeg_path": "ffmpeg.exe"},
    )
    runner = WorkerRunner(
        queue=queue,
        handlers={
            "video.frames.generate": VideoFrameHandler(
                service=service,
                generator=lambda **kwargs: f"frame-{kwargs['frame']}".encode(),
                queue=queue,
                ffmpeg_path="ffmpeg.exe",
            )
        },
        worker_id="video-worker",
    )

    assert runner.run_once()

    with Session(service.engine) as session:
        assert session.query(Job).filter_by(kind="video.stitch").count() == 1


def test_video_frame_worker_stops_without_persisting_or_stitching_after_cancel(
    tmp_path: Path,
) -> None:
    service, queue = make_service_and_queue(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(title="demo", description="turn", reference_images=[])
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
            segments=[{"start_frame": 0, "end_frame": 3, "motion": "turn"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)
    job_id = queue.enqueue("video.frames.generate", {"project_id": project_id})

    def cancel_after_first_result(**kwargs: object) -> bytes:
        queue.cancel(job_id)
        return f"frame-{kwargs['frame']}".encode()

    runner = WorkerRunner(
        queue=queue,
        handlers={
            "video.frames.generate": VideoFrameHandler(
                service=service,
                generator=cancel_after_first_result,
                queue=queue,
                ffmpeg_path="ffmpeg.exe",
            )
        },
        worker_id="video-worker",
    )

    assert runner.run_once()

    assert queue.get(job_id).status == JobStatus.CANCELLED
    with Session(service.engine) as session:
        assert session.query(VideoFrame).count() == 0
        assert session.query(Job).filter_by(kind="video.stitch").count() == 0


def test_video_stitch_worker_outputs_completed_mp4(
    tmp_path: Path,
) -> None:
    service, queue = make_service_and_queue(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(title="demo", description="turn", reference_images=[])
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
            segments=[{"start_frame": 0, "end_frame": 2, "motion": "turn"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)
    service.generate_intermediate_frames(
        project_id, generator=lambda **kwargs: f"frame-{kwargs['frame']}".encode()
    )
    job_id = queue.enqueue(
        "video.stitch",
        {"project_id": project_id, "ffmpeg_path": "ffmpeg.exe"},
    )
    commands: list[list[str]] = []
    runner = WorkerRunner(
        queue=queue,
        handlers={
            "video.stitch": VideoStitchHandler(
                service=service,
                runner=lambda command: commands.append(command),
            )
        },
        worker_id="video-worker",
    )

    assert runner.run_once()

    assert queue.get(job_id).status == JobStatus.COMPLETED
    assert commands and commands[0][0] == "ffmpeg.exe"
    with Session(service.engine) as session:
        project = session.get(VideoProject, project_id)
        assert project is not None
        assert project.status == "completed"


def test_video_stitch_worker_does_not_complete_or_keep_temp_output_after_cancel(
    tmp_path: Path,
) -> None:
    service, queue = make_service_and_queue(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(title="demo", description="turn", reference_images=[])
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
            segments=[{"start_frame": 0, "end_frame": 2, "motion": "turn"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)
    service.generate_intermediate_frames(
        project_id, generator=lambda **kwargs: f"frame-{kwargs['frame']}".encode()
    )
    job_id = queue.enqueue(
        "video.stitch",
        {"project_id": project_id, "ffmpeg_path": "ffmpeg.exe"},
    )

    def cancel_after_output(command: list[str]) -> None:
        output_path = Path(command[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"mp4")
        queue.cancel(job_id)

    runner = WorkerRunner(
        queue=queue,
        handlers={
            "video.stitch": VideoStitchHandler(
                service=service,
                runner=cancel_after_output,
                queue=queue,
            )
        },
        worker_id="video-worker",
    )

    assert runner.run_once()

    assert queue.get(job_id).status == JobStatus.CANCELLED
    with Session(service.engine) as session:
        project = session.get(VideoProject, project_id)
        assert project is not None
        assert project.status == "stitching"
        assert "output_video_path" not in project.settings
    output_dir = tmp_path / "data" / "video_projects" / project_id / "output"
    assert not (output_dir / "video.mp4").exists()
    assert not (output_dir / "video.tmp.mp4").exists()


def test_video_frame_repair_worker_repairs_selected_frame(
    tmp_path: Path,
) -> None:
    service, queue = make_service_and_queue(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(title="demo", description="turn", reference_images=[])
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
            segments=[{"start_frame": 0, "end_frame": 2, "motion": "turn"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)
    service.generate_intermediate_frames(
        project_id, generator=lambda **kwargs: f"frame-{kwargs['frame']}".encode()
    )
    job_id = queue.enqueue(
        "video.frame.repair",
        {"project_id": project_id, "frame": 1},
    )
    repaired_frames: list[int] = []
    runner = WorkerRunner(
        queue=queue,
        handlers={
            "video.frame.repair": VideoFrameRepairHandler(
                service=service,
                generator=lambda **kwargs: repaired_frames.append(kwargs["frame"])
                or b"repaired",
            )
        },
        worker_id="video-worker",
    )

    assert runner.run_once()

    assert queue.get(job_id).status == JobStatus.COMPLETED
    assert repaired_frames == [1]
    with Session(service.engine) as session:
        frame = session.query(VideoFrame).filter_by(frame=1).one()
        assert frame.status == "completed"
        assert Path(frame.path).read_bytes() == b"repaired"


def test_video_frame_repair_worker_does_not_overwrite_after_cancel(
    tmp_path: Path,
) -> None:
    service, queue = make_service_and_queue(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(title="demo", description="turn", reference_images=[])
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
            segments=[{"start_frame": 0, "end_frame": 2, "motion": "turn"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)
    service.generate_intermediate_frames(
        project_id, generator=lambda **kwargs: b"original"
    )
    job_id = queue.enqueue(
        "video.frame.repair",
        {"project_id": project_id, "frame": 1},
    )

    def cancel_after_result(**kwargs: object) -> bytes:
        del kwargs
        queue.cancel(job_id)
        return b"replacement"

    runner = WorkerRunner(
        queue=queue,
        handlers={
            "video.frame.repair": VideoFrameRepairHandler(
                service=service,
                generator=cancel_after_result,
                queue=queue,
            )
        },
        worker_id="video-worker",
    )

    assert runner.run_once()

    assert queue.get(job_id).status == JobStatus.CANCELLED
    with Session(service.engine) as session:
        frame = session.query(VideoFrame).filter_by(frame=1).one()
        assert Path(frame.path).read_bytes() == b"original"


def test_video_keyframe_worker_marks_upstream_request_sent_after_direct_task_creation(
    tmp_path: Path,
) -> None:
    service, queue = make_service_and_queue(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(title="demo", description="turn", reference_images=[])
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
    job_id = queue.enqueue("video.keyframes.generate", {"project_id": project_id})
    job = queue.claim_next("video-worker")
    assert job is not None

    def direct_generator(
        prompt: str, *, task_id: str | None, on_task_created: object
    ) -> bytes:
        del prompt, task_id
        assert callable(on_task_created)
        on_task_created("task-keyframe")
        assert queue.get(job_id).upstream_request_sent is True
        raise RuntimeError("stop after mark")

    handler = VideoKeyframeHandler(
        service=service,
        generator=type("DirectGenerator", (), {"generate": staticmethod(direct_generator)})(),
        queue=queue,
    )

    with pytest.raises(RuntimeError, match="stop after mark"):
        handler.handle(job, worker_id="video-worker")


def test_video_keyframe_regenerate_worker_marks_upstream_request_sent_when_reusing_task(
    tmp_path: Path,
) -> None:
    service, queue = make_service_and_queue(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(title="demo", description="turn", reference_images=[])
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
    service.generate_keyframes(project_id, lambda prompt: prompt.encode())
    with Session(service.engine) as session:
        keyframe = session.query(VideoKeyframe).filter_by(frame=0).one()
        keyframe.upstream_task_id = "existing-keyframe-task"
        session.commit()
    job_id = queue.enqueue(
        "video.keyframe.regenerate",
        {"project_id": project_id, "frame": 0},
    )
    job = queue.claim_next("video-worker")
    assert job is not None

    def direct_generator(
        prompt: str, *, task_id: str | None, on_task_created: object
    ) -> bytes:
        del prompt, on_task_created
        assert task_id == "existing-keyframe-task"
        assert queue.get(job_id).upstream_request_sent is True
        raise RuntimeError("stop after mark")

    handler = VideoKeyframeRegenerateHandler(
        service=service,
        generator=type("DirectGenerator", (), {"generate": staticmethod(direct_generator)})(),
        queue=queue,
    )

    with pytest.raises(RuntimeError, match="stop after mark"):
        handler.handle(job, worker_id="video-worker")


def test_video_frame_worker_marks_upstream_request_sent_after_direct_task_creation(
    tmp_path: Path,
) -> None:
    service, queue = make_service_and_queue(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(title="demo", description="turn", reference_images=[])
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
            segments=[{"start_frame": 0, "end_frame": 2, "motion": "turn"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)
    job_id = queue.enqueue("video.frames.generate", {"project_id": project_id})
    job = queue.claim_next("video-worker")
    assert job is not None

    def direct_generator(**kwargs: object) -> bytes:
        on_task_created = kwargs["on_task_created"]
        assert callable(on_task_created)
        on_task_created("task-frame")
        assert queue.get(job_id).upstream_request_sent is True
        raise RuntimeError("stop after mark")

    handler = VideoFrameHandler(
        service=service,
        generator=type("DirectGenerator", (), {"generate": staticmethod(direct_generator)})(),
        queue=queue,
    )

    with pytest.raises(RuntimeError, match="stop after mark"):
        handler.handle(job, worker_id="video-worker")


def test_video_frame_repair_worker_marks_upstream_request_sent_when_reusing_task(
    tmp_path: Path,
) -> None:
    service, queue = make_service_and_queue(tmp_path)
    project_id = service.create_draft(
        VideoProjectDraftRequest(title="demo", description="turn", reference_images=[])
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
            segments=[{"start_frame": 0, "end_frame": 2, "motion": "turn"}],
        ),
    )
    service.confirm_storyboard(project_id, version_id)
    service.generate_keyframes(project_id, lambda prompt: prompt.encode())
    service.confirm_keyframes(project_id)
    service.generate_intermediate_frames(
        project_id, generator=lambda **kwargs: f"frame-{kwargs['frame']}".encode()
    )
    with Session(service.engine) as session:
        frame = session.query(VideoFrame).filter_by(frame=1).one()
        frame.upstream_task_id = "existing-frame-task"
        session.commit()
    job_id = queue.enqueue(
        "video.frame.repair",
        {"project_id": project_id, "frame": 1},
    )
    job = queue.claim_next("video-worker")
    assert job is not None

    def direct_generator(**kwargs: object) -> bytes:
        assert kwargs["task_id"] == "existing-frame-task"
        assert queue.get(job_id).upstream_request_sent is True
        raise RuntimeError("stop after mark")

    handler = VideoFrameRepairHandler(
        service=service,
        generator=type("DirectGenerator", (), {"generate": staticmethod(direct_generator)})(),
        queue=queue,
    )

    with pytest.raises(RuntimeError, match="stop after mark"):
        handler.handle(job, worker_id="video-worker")
