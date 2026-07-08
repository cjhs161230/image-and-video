from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from image_video.application.history import HistoryService
from image_video.domain.jobs import JobStatus
from image_video.infrastructure.database.engine import create_database_engine, initialize_database
from image_video.infrastructure.database.models import (
    Job,
    JobEvent,
    MediaAsset,
    VideoFrame,
    VideoKeyframe,
    VideoProject,
    VideoStoryboardVersion,
)


def make_history(tmp_path: Path) -> HistoryService:
    engine = create_database_engine(tmp_path / "history.db")
    initialize_database(engine)
    return HistoryService(engine, data_root=tmp_path / "data")


def test_history_lists_images_and_completed_videos_with_filters(tmp_path: Path) -> None:
    service = make_history(tmp_path)
    now = datetime.now(UTC)
    image_path = tmp_path / "data" / "image.png"
    thumb_path = tmp_path / "data" / "thumb.jpg"
    video_path = tmp_path / "data" / "video.mp4"
    for path in [image_path, thumb_path, video_path]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"media")

    with Session(service.engine) as session:
        session.add(
            Job(
                id="job-1",
                kind="image.generate",
                payload={"prompt": "cat"},
                status=JobStatus.COMPLETED,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            MediaAsset(
                id="media-1",
                job_id="job-1",
                media_type="image",
                path=image_path.as_posix(),
                thumbnail_path=thumb_path.as_posix(),
                width=512,
                height=512,
                file_size_bytes=5,
                sha256="0" * 64,
                created_at=now,
            )
        )
        session.add(
            VideoProject(
                id="project-1",
                title="video",
                description="walk",
                status="completed",
                settings={"output_video_path": video_path.as_posix()},
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            Job(
                id="video-job-1",
                kind="video.stitch",
                payload={"project_id": "project-1"},
                status=JobStatus.COMPLETED,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            JobEvent(
                job_id="video-job-1",
                event="completed",
                data={},
                created_at=now,
            )
        )
        session.commit()

    all_items = service.list_history()
    videos = service.list_history(kind="video")

    assert [item["kind"] for item in all_items] == ["image", "video"]
    assert "path" not in all_items[0]
    assert all_items[0]["media_url"] == "/api/v1/media/media-1"
    assert all_items[0]["thumbnail_url"] == "/api/v1/media/media-1"
    assert "path" not in all_items[1]
    assert all_items[1]["media_url"] == "/api/v1/video-projects/project-1/output"
    assert all_items[1]["cover_url"] == ""
    assert all_items[1]["log_summary"] == "任务：completed；最近事件：completed"
    assert [item["id"] for item in videos] == ["project-1"]


def test_video_history_lists_all_project_states_with_continue_metadata(
    tmp_path: Path,
) -> None:
    service = make_history(tmp_path)
    now = datetime.now(UTC)
    output_path = tmp_path / "data" / "video_projects" / "completed" / "output" / "video.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"mp4")
    states = [
        "draft",
        "awaiting_storyboard_approval",
        "generating_frames",
        "failed",
        "completed",
    ]
    with Session(service.engine) as session:
        for index, status in enumerate(states):
            project_id = f"project-{status}"
            session.add(
                VideoProject(
                    id=project_id,
                    title=f"title {status}",
                    description=f"description {status}",
                    status=status,
                    settings=(
                        {"output_video_path": output_path.as_posix()}
                        if status == "completed"
                        else {}
                    ),
                    created_at=now,
                    updated_at=now.replace(microsecond=index),
                )
            )
        session.add(
            Job(
                id="failed-job",
                kind="video.frames.generate",
                payload={"project_id": "project-failed"},
                status=JobStatus.FAILED,
                error_code="HTTPSTATUSERROR",
                error_message="上游 HTTP 502",
                created_at=now,
                updated_at=now.replace(microsecond=10),
            )
        )
        session.commit()

    videos = service.list_history(kind="video")

    assert [item["id"] for item in videos] == [
        "project-completed",
        "project-failed",
        "project-generating_frames",
        "project-awaiting_storyboard_approval",
        "project-draft",
    ]
    failed = next(item for item in videos if item["id"] == "project-failed")
    assert failed["status"] == "failed"
    assert failed["title"] == "title failed"
    assert failed["description"] == "description failed"
    assert failed["project_url"] == "/api/v1/video-projects/project-failed"
    assert failed["can_continue"] is False
    assert failed["archived_message"] == "视频功能已归档，当前默认不可用。"
    assert failed["media_url"] == ""
    assert failed["updated_at"] == now.replace(microsecond=3, tzinfo=None).isoformat()
    assert failed["latest_job_status"] == "failed"
    assert failed["latest_job_error"] == "上游 HTTP 502"
    completed = videos[0]
    assert completed["media_url"] == "/api/v1/video-projects/project-completed/output"


def test_video_history_uses_first_keyframe_as_controlled_cover(tmp_path: Path) -> None:
    service = make_history(tmp_path)
    now = datetime.now(UTC)
    cover_path = tmp_path / "data" / "videos" / "project-1" / "keyframe_000000.png"
    cover_path.parent.mkdir(parents=True, exist_ok=True)
    cover_path.write_bytes(b"cover")
    with Session(service.engine) as session:
        session.add(
            VideoProject(
                id="project-1",
                title="video",
                description="walk",
                status="completed",
                settings={},
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            VideoStoryboardVersion(
                id="version-1",
                project_id="project-1",
                version=1,
                source="user",
                plan={},
                suggestion="",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            VideoKeyframe(
                id="keyframe-1",
                project_id="project-1",
                storyboard_version_id="version-1",
                frame=0,
                prompt="start",
                description="start",
                path=cover_path.as_posix(),
                status="completed",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    [video] = service.list_history(kind="video")

    assert video["cover_url"] == "/api/v1/video-projects/project-1/keyframes/0/media"
    assert video["thumbnail_url"] == "/api/v1/video-projects/project-1/keyframes/0/media"
    assert "path" not in video


def test_resolve_video_output_allows_only_registered_data_mp4(tmp_path: Path) -> None:
    service = make_history(tmp_path)
    now = datetime.now(UTC)
    safe_output = tmp_path / "data" / "video_projects" / "project-safe" / "output" / "video.mp4"
    outside_output = tmp_path / "outside.mp4"
    safe_output.parent.mkdir(parents=True, exist_ok=True)
    safe_output.write_bytes(b"mp4")
    outside_output.write_bytes(b"outside")
    with Session(service.engine) as session:
        session.add_all(
            [
                VideoProject(
                    id="project-safe",
                    title="safe",
                    description="safe",
                    status="completed",
                    settings={"output_video_path": safe_output.as_posix()},
                    created_at=now,
                    updated_at=now,
                ),
                VideoProject(
                    id="project-outside",
                    title="outside",
                    description="outside",
                    status="completed",
                    settings={"output_video_path": outside_output.as_posix()},
                    created_at=now,
                    updated_at=now,
                ),
                VideoProject(
                    id="project-missing",
                    title="missing",
                    description="missing",
                    status="completed",
                    settings={},
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        session.commit()

    assert service.resolve_video_output_path("project-safe") == safe_output.resolve()
    assert service.resolve_video_output_path("project-outside") is None
    assert service.resolve_video_output_path("project-missing") is None


def test_image_history_summary_uses_latest_persisted_job_event(tmp_path: Path) -> None:
    service = make_history(tmp_path)
    now = datetime.now(UTC)
    image_path = tmp_path / "data" / "image.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"image")
    with Session(service.engine) as session:
        session.add(
            Job(
                id="job-events",
                kind="image.generate",
                payload={},
                status=JobStatus.COMPLETED,
                created_at=now,
                updated_at=now,
            )
        )
        session.add_all(
            [
                JobEvent(
                    job_id="job-events",
                    event="queued",
                    data={},
                    created_at=now,
                ),
                JobEvent(
                    job_id="job-events",
                    event="completed",
                    data={},
                    created_at=now,
                ),
            ]
        )
        session.add(
            MediaAsset(
                id="media-events",
                job_id="job-events",
                media_type="image",
                path=image_path.as_posix(),
                thumbnail_path=image_path.as_posix(),
                width=1,
                height=1,
                file_size_bytes=5,
                sha256="4" * 64,
                created_at=now,
            )
        )
        session.commit()

    [item] = service.list_history(kind="image")

    assert item["log_summary"] == "任务：completed；最近事件：completed"


def test_resolve_media_allows_only_registered_paths_under_data(tmp_path: Path) -> None:
    service = make_history(tmp_path)
    now = datetime.now(UTC)
    safe_path = tmp_path / "data" / "safe.png"
    unsafe_path = tmp_path / "outside.png"
    safe_path.parent.mkdir(parents=True, exist_ok=True)
    safe_path.write_bytes(b"safe")
    unsafe_path.write_bytes(b"unsafe")
    with Session(service.engine) as session:
        session.add(
            Job(
                id="job-1",
                kind="image.generate",
                payload={},
                status=JobStatus.COMPLETED,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            MediaAsset(
                id="safe",
                job_id="job-1",
                media_type="image",
                path=safe_path.as_posix(),
                thumbnail_path=safe_path.as_posix(),
                width=1,
                height=1,
                file_size_bytes=4,
                sha256="0" * 64,
                created_at=now,
            )
        )
        session.add(
            MediaAsset(
                id="unsafe",
                job_id="job-1",
                media_type="image",
                path=unsafe_path.as_posix(),
                thumbnail_path=unsafe_path.as_posix(),
                width=1,
                height=1,
                file_size_bytes=6,
                sha256="1" * 64,
                created_at=now,
            )
        )
        session.commit()

    assert service.resolve_media_path("safe") == safe_path.resolve()
    assert service.resolve_media_path("missing") is None
    assert service.resolve_media_path("unsafe") is None


def test_delete_media_requires_confirmation_and_keeps_record_on_file_failure(
    tmp_path: Path,
) -> None:
    service = make_history(tmp_path)
    now = datetime.now(UTC)
    media_path = tmp_path / "data" / "delete.png"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"delete")
    with Session(service.engine) as session:
        session.add(
            Job(
                id="job-delete",
                kind="image.generate",
                payload={},
                status=JobStatus.COMPLETED,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            MediaAsset(
                id="delete-media",
                job_id="job-delete",
                media_type="image",
                path=media_path.as_posix(),
                thumbnail_path=media_path.as_posix(),
                width=1,
                height=1,
                file_size_bytes=6,
                sha256="2" * 64,
                created_at=now,
            )
        )
        session.commit()

    assert service.delete_media("delete-media", confirm=False)["status"] == "confirmation_required"
    failed = service.delete_media(
        "delete-media",
        confirm=True,
        unlink=lambda path: (_ for _ in ()).throw(PermissionError("locked")),
    )
    assert failed["status"] == "partial_failed"
    assert service.resolve_media_path("delete-media") == media_path.resolve()

    deleted = service.delete_media("delete-media", confirm=True)

    assert deleted["status"] == "deleted"
    assert not media_path.exists()
    assert service.resolve_media_path("delete-media") is None


def test_delete_media_rejects_thumbnail_outside_data_root(tmp_path: Path) -> None:
    service = make_history(tmp_path)
    now = datetime.now(UTC)
    media_path = tmp_path / "data" / "safe.png"
    outside_thumbnail = tmp_path / "outside-thumbnail.jpg"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"safe")
    outside_thumbnail.write_bytes(b"outside")
    with Session(service.engine) as session:
        session.add(
            Job(
                id="job-outside-thumbnail",
                kind="image.generate",
                payload={},
                status=JobStatus.COMPLETED,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            MediaAsset(
                id="outside-thumbnail",
                job_id="job-outside-thumbnail",
                media_type="image",
                path=media_path.as_posix(),
                thumbnail_path=outside_thumbnail.as_posix(),
                width=1,
                height=1,
                file_size_bytes=4,
                sha256="3" * 64,
                created_at=now,
            )
        )
        session.commit()

    result = service.delete_media("outside-thumbnail", confirm=True)

    assert result["status"] == "partial_failed"
    assert media_path.exists()
    assert outside_thumbnail.exists()
    with Session(service.engine) as session:
        assert session.get(MediaAsset, "outside-thumbnail") is not None


def test_delete_video_project_requires_confirmation_and_removes_project_files(
    tmp_path: Path,
) -> None:
    service = make_history(tmp_path)
    now = datetime.now(UTC)
    project_dir = tmp_path / "data" / "video_projects" / "project-delete"
    keyframe_path = project_dir / "keyframes" / "keyframe_000000.png"
    frame_path = project_dir / "frames" / "frame_000001.png"
    output_path = project_dir / "output" / "video.mp4"
    for path in [keyframe_path, frame_path, output_path]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(path.name.encode())
    with Session(service.engine) as session:
        session.add(
            VideoProject(
                id="project-delete",
                title="delete",
                description="delete",
                status="completed",
                settings={"output_video_path": output_path.as_posix()},
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            VideoStoryboardVersion(
                id="version-delete",
                project_id="project-delete",
                version=1,
                source="user",
                plan={},
                suggestion="",
                created_at=now,
            )
        )
        session.flush()
        session.add_all(
            [
                VideoKeyframe(
                    id="keyframe-delete",
                    project_id="project-delete",
                    storyboard_version_id="version-delete",
                    frame=0,
                    prompt="start",
                    description="start",
                    path=keyframe_path.as_posix(),
                    status="completed",
                    created_at=now,
                    updated_at=now,
                ),
                VideoFrame(
                    id="frame-delete",
                    project_id="project-delete",
                    frame=1,
                    segment_start_frame=0,
                    segment_end_frame=2,
                    prompt="middle",
                    path=frame_path.as_posix(),
                    status="completed",
                    error_message="",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        session.commit()

    assert service.delete_video_project("project-delete", confirm=False)["status"] == (
        "confirmation_required"
    )
    deleted = service.delete_video_project("project-delete", confirm=True)

    assert deleted["status"] == "deleted"
    assert not keyframe_path.exists()
    assert not frame_path.exists()
    assert not output_path.exists()
    assert not project_dir.exists()
    with Session(service.engine) as session:
        assert session.get(VideoProject, "project-delete") is None


def test_delete_video_project_keeps_record_on_file_failure(tmp_path: Path) -> None:
    service = make_history(tmp_path)
    now = datetime.now(UTC)
    output_path = tmp_path / "data" / "video_projects" / "project-locked" / "output" / "video.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"mp4")
    with Session(service.engine) as session:
        session.add(
            VideoProject(
                id="project-locked",
                title="locked",
                description="locked",
                status="completed",
                settings={"output_video_path": output_path.as_posix()},
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    failed = service.delete_video_project(
        "project-locked",
        confirm=True,
        unlink=lambda path: (_ for _ in ()).throw(PermissionError(f"locked {path.name}")),
    )

    assert failed["status"] == "partial_failed"
    assert output_path.exists()
    with Session(service.engine) as session:
        assert session.get(VideoProject, "project-locked") is not None


def test_delete_video_project_rejects_output_outside_data_root(tmp_path: Path) -> None:
    service = make_history(tmp_path)
    now = datetime.now(UTC)
    outside_output = tmp_path / "outside.mp4"
    outside_output.write_bytes(b"outside")
    with Session(service.engine) as session:
        session.add(
            VideoProject(
                id="project-outside-delete",
                title="outside",
                description="outside",
                status="completed",
                settings={"output_video_path": outside_output.as_posix()},
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    result = service.delete_video_project("project-outside-delete", confirm=True)

    assert result["status"] == "partial_failed"
    assert outside_output.exists()
    with Session(service.engine) as session:
        assert session.get(VideoProject, "project-outside-delete") is not None


def test_storage_estimate_uses_real_media_samples_with_fallback(tmp_path: Path) -> None:
    service = make_history(tmp_path)
    now = datetime.now(UTC)
    image_path = tmp_path / "data" / "image.png"
    keyframe_path = tmp_path / "data" / "video_projects" / "project-1" / "keyframes" / "0.png"
    frame_path = tmp_path / "data" / "video_projects" / "project-1" / "frames" / "1.png"
    output_path = tmp_path / "data" / "video_projects" / "project-1" / "output" / "video.mp4"
    samples = {
        image_path: b"i" * 4,
        keyframe_path: b"k" * 10,
        frame_path: b"f" * 20,
        output_path: b"m" * 30,
    }
    for path, content in samples.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    with Session(service.engine) as session:
        session.add(
            Job(
                id="job-estimate",
                kind="image.generate",
                payload={},
                status=JobStatus.COMPLETED,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            MediaAsset(
                id="estimate-media",
                job_id="job-estimate",
                media_type="image",
                path=image_path.as_posix(),
                thumbnail_path=image_path.as_posix(),
                width=1,
                height=1,
                file_size_bytes=4,
                sha256="5" * 64,
                created_at=now,
            )
        )
        session.add(
            VideoProject(
                id="project-1",
                title="estimate",
                description="estimate",
                status="completed",
                settings={"output_video_path": output_path.as_posix()},
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            VideoStoryboardVersion(
                id="version-estimate",
                project_id="project-1",
                version=1,
                source="user",
                plan={},
                suggestion="",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            VideoKeyframe(
                id="keyframe-estimate",
                project_id="project-1",
                storyboard_version_id="version-estimate",
                frame=0,
                prompt="start",
                description="start",
                path=keyframe_path.as_posix(),
                status="completed",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            VideoFrame(
                id="frame-estimate",
                project_id="project-1",
                frame=1,
                segment_start_frame=0,
                segment_end_frame=2,
                prompt="middle",
                path=frame_path.as_posix(),
                status="completed",
                error_message="",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    estimate = service.storage_estimate()
    empty = make_history(tmp_path / "empty").storage_estimate()

    assert estimate["source"] == "real"
    assert estimate["image_mb_per_item"] == round(4 / 1024 / 1024, 4)
    assert estimate["video_frame_mb_per_item"] == round(15 / 1024 / 1024, 4)
    assert estimate["video_output_mb_per_project"] == round(30 / 1024 / 1024, 4)
    assert empty["source"] == "fallback"
    assert empty["image_mb_per_item"] == 12
    assert empty["video_frame_mb_per_item"] == 12
