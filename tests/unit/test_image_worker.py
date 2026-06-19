from io import BytesIO
from pathlib import Path

from PIL import Image

from image_video.application.image_jobs import ImageJobRequest, ImageJobService
from image_video.domain.jobs import JobStatus
from image_video.infrastructure.database.engine import create_database_engine, initialize_database
from image_video.infrastructure.database.media import MediaRepository
from image_video.infrastructure.database.queue import JobQueue
from image_video.infrastructure.providers.dashscope import DashScopeResult
from image_video.infrastructure.providers.matsca import GeneratedImage
from image_video.worker.image_handler import ImageJobHandler


def png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (64, 32), "red").save(output, format="PNG")
    return output.getvalue()


class FakeMatscaProvider:
    edited_images: list[bytes] | None = None

    def generate(self, **kwargs: object) -> list[GeneratedImage]:
        del kwargs
        return [GeneratedImage(content=png_bytes())]

    def edit(self, **kwargs: object) -> list[GeneratedImage]:
        self.edited_images = kwargs["images"]  # type: ignore[assignment]
        return [GeneratedImage(content=png_bytes())]


class FakeDashScopeProvider:
    def generate(self, **kwargs: object) -> DashScopeResult:
        del kwargs
        return DashScopeResult(
            request_id="req",
            image_urls=["https://cdn.test/image.png"],
            input_tokens=1,
            width=64,
            height=32,
            raw={},
        )

def test_image_handler_saves_media_thumbnail_and_completes_job(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "workbench.db")
    initialize_database(engine)
    queue = JobQueue(engine)
    service = ImageJobService(queue)
    job_id = service.submit(
        ImageJobRequest(model="gpt-image-2", prompt="cat", output_format="png")
    )
    claimed = queue.claim_next("worker-a")
    assert claimed is not None
    handler = ImageJobHandler(
        queue=queue,
        media=MediaRepository(engine),
        output_root=tmp_path / "outputs",
        matsca_provider=lambda mode: FakeMatscaProvider(),
    )

    handler.handle(claimed, worker_id="worker-a")

    assert queue.get(job_id).status == JobStatus.COMPLETED
    assets = MediaRepository(engine).for_job(job_id)
    assert len(assets) == 1
    assert Path(assets[0].path).read_bytes() == png_bytes()
    assert Path(assets[0].thumbnail_path).is_file()
    assert assets[0].width == 64
    assert assets[0].height == 32


def test_image_handler_uses_reference_media_for_gpt_edit(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "workbench.db")
    initialize_database(engine)
    queue = JobQueue(engine)
    media = MediaRepository(engine)
    source_job = queue.enqueue("image.generate", {})
    source_path = tmp_path / "source.png"
    source_path.write_bytes(png_bytes())
    source_thumb = tmp_path / "source-thumb.jpg"
    source_thumb.write_bytes(b"thumb")
    media_id = media.record_image(
        job_id=source_job,
        model="gpt-image-2",
        prompt="source",
        parameters={},
        path=source_path,
        thumbnail_path=source_thumb,
        width=64,
        height=32,
        sha256="hash",
    )
    queue.cancel(source_job)
    service = ImageJobService(queue)
    job_id = service.submit(
        ImageJobRequest(
            model="gpt-image-2",
            prompt="edit",
            input_media_ids=[media_id],
        )
    )
    claimed = queue.claim_next("worker-a")
    assert claimed is not None and claimed.id == job_id
    provider = FakeMatscaProvider()
    handler = ImageJobHandler(
        queue=queue,
        media=media,
        output_root=tmp_path / "outputs",
        matsca_provider=lambda mode: provider,
    )

    handler.handle(claimed, worker_id="worker-a")

    assert provider.edited_images == [png_bytes()]


def test_image_handler_runs_legacy_dashscope_model(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "workbench.db")
    initialize_database(engine)
    queue = JobQueue(engine)
    service = ImageJobService(queue)
    job_id = service.submit(ImageJobRequest(model="wan2.7-image", prompt="cat"))
    claimed = queue.claim_next("worker-a")
    assert claimed is not None and claimed.id == job_id
    handler = ImageJobHandler(
        queue=queue,
        media=MediaRepository(engine),
        output_root=tmp_path / "outputs",
        matsca_provider=lambda mode: FakeMatscaProvider(),
        dashscope_provider=lambda: FakeDashScopeProvider(),
        downloader=lambda url: png_bytes(),
    )

    handler.handle(claimed, worker_id="worker-a")

    assert queue.get(job_id).status == JobStatus.COMPLETED
    assert len(MediaRepository(engine).for_job(job_id)) == 1
