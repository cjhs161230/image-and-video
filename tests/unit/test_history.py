from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from image_video.application.history import HistoryService
from image_video.domain.jobs import JobStatus
from image_video.infrastructure.database.engine import create_database_engine, initialize_database
from image_video.infrastructure.database.models import (
    Job,
    MediaAsset,
    VideoProject,
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
        session.commit()

    all_items = service.list_history()
    videos = service.list_history(kind="video")

    assert [item["kind"] for item in all_items] == ["image", "video"]
    assert all_items[0]["thumbnail_path"] == thumb_path.as_posix()
    assert all_items[1]["cover_path"] == video_path.as_posix()
    assert all_items[1]["log_summary"] == "状态：completed"
    assert [item["id"] for item in videos] == ["project-1"]


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
