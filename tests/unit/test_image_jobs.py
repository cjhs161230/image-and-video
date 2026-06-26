from pathlib import Path

import pytest

from image_video.application.image_jobs import ImageJobRequest, ImageJobService
from image_video.domain.jobs import JobStatus
from image_video.infrastructure.database.engine import create_database_engine, initialize_database
from image_video.infrastructure.database.queue import JobQueue


def make_service(tmp_path: Path) -> tuple[ImageJobService, JobQueue]:
    engine = create_database_engine(tmp_path / "jobs.db")
    initialize_database(engine)
    queue = JobQueue(engine)
    return ImageJobService(queue), queue


def test_image_job_validates_supported_models_and_counts(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path)

    with pytest.raises(ValueError, match="不支持的模型"):
        service.submit(ImageJobRequest(model="unknown", prompt="cat"))

    with pytest.raises(ValueError, match="1 到 4"):
        service.submit(ImageJobRequest(model="gpt-image-2", prompt="cat", n=5))


def test_image_job_validates_gpt_reference_limit(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path)

    with pytest.raises(ValueError, match="最多 8"):
        service.submit(
            ImageJobRequest(
                model="gpt-image-2",
                prompt="cat",
                input_media_ids=[str(index) for index in range(9)],
            )
        )


def test_image_job_normalizes_auto_size_and_rejects_invalid_size(tmp_path: Path) -> None:
    service, queue = make_service(tmp_path)

    job_id = service.submit(
        ImageJobRequest(model="gpt-image-2", prompt="cat", size="")
    )

    assert queue.get(job_id).payload["size"] == "auto"

    with pytest.raises(ValueError, match="size"):
        service.submit(ImageJobRequest(model="gpt-image-2", prompt="cat", size="0x1024"))


def test_submit_persists_normalized_image_job(tmp_path: Path) -> None:
    service, queue = make_service(tmp_path)

    job_id = service.submit(
        ImageJobRequest(
            model="gpt-image-2",
            prompt="cat",
            n=2,
            size="1024x1024",
            quality="medium",
            output_format="png",
            matsca_mode="direct",
            moderation="low",
            output_compression=42,
        )
    )

    job = queue.get(job_id)
    assert job.status == JobStatus.QUEUED
    assert job.kind == "image.generate"
    assert job.payload["model"] == "gpt-image-2"
    assert job.payload["n"] == 2
    assert job.payload["moderation"] == "low"
    assert job.payload["output_compression"] == 42
