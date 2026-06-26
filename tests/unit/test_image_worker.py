from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from image_video.application.image_jobs import ImageJobRequest, ImageJobService
from image_video.domain.jobs import JobStatus
from image_video.infrastructure.database.engine import create_database_engine, initialize_database
from image_video.infrastructure.database.media import MediaRepository
from image_video.infrastructure.database.queue import JobQueue
from image_video.infrastructure.providers.dashscope import DashScopeResult
from image_video.infrastructure.providers.matsca import GeneratedImage, MatscaImageTask
from image_video.worker.image_handler import ImageJobHandler
from image_video.worker.runner import WorkerRunner


def png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (64, 32), "red").save(output, format="PNG")
    return output.getvalue()


def fake_downloader(url: str, *, proxy: str | None = None) -> bytes:
    del url, proxy
    return png_bytes()


class FakeMatscaProvider:
    edited_images: list[bytes] | None = None

    def generate(self, **kwargs: object) -> list[GeneratedImage]:
        del kwargs
        return [GeneratedImage(content=png_bytes())]

    def create_generation_task(self, **kwargs: object) -> MatscaImageTask:
        del kwargs
        return MatscaImageTask(id="task-1", status="queued", images=[])

    def get_image_task(self, task_id: str) -> MatscaImageTask:
        assert task_id == "task-1"
        return MatscaImageTask(
            id="task-1",
            status="completed",
            images=[GeneratedImage(content=png_bytes())],
        )

    def edit(self, **kwargs: object) -> list[GeneratedImage]:
        self.edited_images = kwargs["images"]  # type: ignore[assignment]
        return [GeneratedImage(content=png_bytes())]


class FakeAsyncMatscaProvider:
    generated_sync = False
    edited_sync = False
    client_task_id = ""
    task_id = "task-1"

    def generate(self, **kwargs: object) -> list[GeneratedImage]:
        del kwargs
        self.generated_sync = True
        raise AssertionError("direct text-to-image should use async image tasks")

    def create_generation_task(self, **kwargs: object) -> MatscaImageTask:
        self.client_task_id = str(kwargs["client_task_id"])
        return MatscaImageTask(id=self.task_id, status="queued", images=[])

    def get_image_task(self, task_id: str) -> MatscaImageTask:
        assert task_id == self.task_id
        return MatscaImageTask(
            id=self.task_id,
            status="completed",
            images=[GeneratedImage(content=png_bytes())],
        )

    def create_edit_task(self, **kwargs: object) -> MatscaImageTask:
        self.client_task_id = str(kwargs["client_task_id"])
        self.task_id = "task-edit-1"
        return MatscaImageTask(id=self.task_id, status="queued", images=[])

    def edit(self, **kwargs: object) -> list[GeneratedImage]:
        del kwargs
        self.edited_sync = True
        raise AssertionError("direct image edits should use async image tasks")


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


class FakeNativeMatscaProvider:
    def generate(self, **kwargs: object) -> list[GeneratedImage]:
        del kwargs
        return [GeneratedImage(url="https://official.example/image.png")]

    def create_generation_task(self, **kwargs: object) -> MatscaImageTask:
        del kwargs
        raise AssertionError("native mode should use synchronous generation")

    def get_image_task(self, task_id: str) -> MatscaImageTask:
        raise AssertionError(f"native mode should not poll async task {task_id}")

    def edit(self, **kwargs: object) -> list[GeneratedImage]:
        del kwargs
        return [GeneratedImage(url="https://official.example/image.png")]


class RecordingNativeProvider:
    def __init__(self, url: str = "https://official.example/image.png"):
        self.url = url
        self.generate_calls = 0
        self.edit_calls = 0

    def generate(self, **kwargs: object) -> list[GeneratedImage]:
        del kwargs
        self.generate_calls += 1
        return [GeneratedImage(url=self.url)]

    def create_generation_task(self, **kwargs: object) -> MatscaImageTask:
        del kwargs
        raise AssertionError("native mode should use synchronous generation")

    def get_image_task(self, task_id: str) -> MatscaImageTask:
        raise AssertionError(f"native mode should not poll async task {task_id}")

    def edit(self, **kwargs: object) -> list[GeneratedImage]:
        del kwargs
        self.edit_calls += 1
        return [GeneratedImage(url=self.url)]


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


def test_image_handler_uses_async_task_for_direct_text_to_image(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(tmp_path / "workbench.db")
    initialize_database(engine)
    queue = JobQueue(engine)
    media = MediaRepository(engine)
    job_id = ImageJobService(queue).submit(
        ImageJobRequest(
            model="gpt-image-2",
            prompt="cat",
            matsca_mode="direct",
            output_format="png",
        )
    )
    claimed = queue.claim_next("worker-a")
    assert claimed is not None
    provider = FakeAsyncMatscaProvider()
    handler = ImageJobHandler(
        queue=queue,
        media=media,
        output_root=tmp_path / "outputs",
        matsca_provider=lambda mode: provider,
        async_poll_interval=0,
        async_poll_timeout=1,
    )

    handler.handle(claimed, worker_id="worker-a")

    stored = queue.get(job_id)
    assert stored.status == JobStatus.COMPLETED
    assert stored.payload["matsca_task_id"] == "task-1"
    assert provider.client_task_id == f"image-video-{job_id}"
    assert not provider.generated_sync
    assert len(media.for_job(job_id)) == 1


def test_image_handler_uses_native_download_proxy_for_native_url_result(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(tmp_path / "workbench.db")
    initialize_database(engine)
    queue = JobQueue(engine)
    service = ImageJobService(queue)
    job_id = service.submit(
        ImageJobRequest(
            model="gpt-image-2",
            prompt="cat",
            matsca_mode="native",
            output_format="png",
        )
    )
    claimed = queue.claim_next("worker-a")
    assert claimed is not None
    calls: list[tuple[str, str | None]] = []

    def downloader(url: str, *, proxy: str | None = None) -> bytes:
        calls.append((url, proxy))
        return png_bytes()

    handler = ImageJobHandler(
        queue=queue,
        media=MediaRepository(engine),
        output_root=tmp_path / "outputs",
        matsca_provider=lambda mode: FakeNativeMatscaProvider(),
        downloader=downloader,
        native_download_proxy="http://127.0.0.1:7890",
    )

    handler.handle(claimed, worker_id="worker-a")

    assert calls == [
        ("https://official.example/image.png", "http://127.0.0.1:7890")
    ]
    assert queue.get(job_id).status == JobStatus.COMPLETED


def test_native_url_result_is_persisted_before_download_failure(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(tmp_path / "workbench.db")
    initialize_database(engine)
    queue = JobQueue(engine)
    job_id = ImageJobService(queue).submit(
        ImageJobRequest(
            model="gpt-image-2",
            prompt="cat",
            matsca_mode="native",
            output_format="png",
        )
    )
    provider = RecordingNativeProvider()

    def failing_downloader(url: str, *, proxy: str | None = None) -> bytes:
        del url, proxy
        raise ValueError("图片下载失败：网络请求异常")

    handler = ImageJobHandler(
        queue=queue,
        media=MediaRepository(engine),
        output_root=tmp_path / "outputs",
        matsca_provider=lambda mode: provider,
        downloader=failing_downloader,
    )
    runner = WorkerRunner(
        queue=queue,
        handlers={"image.generate": handler},
        worker_id="worker-a",
    )

    assert runner.run_once()

    stored = queue.get(job_id)
    assert stored.status == JobStatus.NEEDS_ATTENTION
    assert stored.error_code == "IMAGE_DOWNLOAD_FAILED"
    assert stored.payload["client_task_id"] == f"image-video-{job_id}"
    assert stored.payload["result_urls"] == ["https://official.example/image.png"]
    assert provider.generate_calls == 1


def test_native_url_resume_downloads_existing_url_without_regenerating(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(tmp_path / "workbench.db")
    initialize_database(engine)
    queue = JobQueue(engine)
    job_id = queue.enqueue(
        "image.generate",
        {
            "model": "gpt-image-2",
            "prompt": "cat",
            "n": 1,
            "size": "1024x1024",
            "quality": "medium",
            "style": "vivid",
            "background": "auto",
            "moderation": "auto",
            "output_format": "png",
            "matsca_mode": "native",
            "input_media_ids": [],
            "client_task_id": "image-video-existing",
            "result_urls": ["https://official.example/retry.png"],
        },
    )
    provider = RecordingNativeProvider()
    downloads: list[str] = []

    def downloader(url: str, *, proxy: str | None = None) -> bytes:
        del proxy
        downloads.append(url)
        return png_bytes()

    handler = ImageJobHandler(
        queue=queue,
        media=MediaRepository(engine),
        output_root=tmp_path / "outputs",
        matsca_provider=lambda mode: provider,
        downloader=downloader,
    )
    runner = WorkerRunner(
        queue=queue,
        handlers={"image.generate": handler},
        worker_id="worker-a",
    )

    assert runner.run_once()

    assert queue.get(job_id).status == JobStatus.COMPLETED
    assert downloads == ["https://official.example/retry.png"]
    assert provider.generate_calls == 0


def test_image_save_failure_is_needs_attention_and_keeps_recovery_payload(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(tmp_path / "workbench.db")
    initialize_database(engine)
    queue = JobQueue(engine)
    job_id = ImageJobService(queue).submit(
        ImageJobRequest(
            model="gpt-image-2",
            prompt="cat",
            matsca_mode="native",
            output_format="png",
        )
    )
    provider = RecordingNativeProvider()

    def downloader(url: str, *, proxy: str | None = None) -> bytes:
        del url, proxy
        return b"not an image"

    handler = ImageJobHandler(
        queue=queue,
        media=MediaRepository(engine),
        output_root=tmp_path / "outputs",
        matsca_provider=lambda mode: provider,
        downloader=downloader,
    )
    runner = WorkerRunner(
        queue=queue,
        handlers={"image.generate": handler},
        worker_id="worker-a",
    )

    assert runner.run_once()

    stored = queue.get(job_id)
    assert stored.status == JobStatus.NEEDS_ATTENTION
    assert stored.error_code == "IMAGE_SAVE_FAILED"
    assert stored.payload["result_urls"] == ["https://official.example/image.png"]
    assert MediaRepository(engine).for_job(job_id) == []


def test_image_handler_uses_native_proxy_only_for_edit_result_download(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(tmp_path / "workbench.db")
    initialize_database(engine)
    queue = JobQueue(engine)
    media = MediaRepository(engine)
    source_job = queue.enqueue("image.generate", {})
    source_path = tmp_path / "source.png"
    source_path.write_bytes(png_bytes())
    media_id = media.record_image(
        job_id=source_job,
        model="gpt-image-2",
        prompt="source",
        parameters={},
        path=source_path,
        thumbnail_path=source_path,
        width=64,
        height=32,
        sha256="hash",
    )
    queue.cancel(source_job)
    job_id = ImageJobService(queue).submit(
        ImageJobRequest(
            model="gpt-image-2",
            prompt="edit",
            matsca_mode="native",
            input_media_ids=[media_id],
        )
    )
    claimed = queue.claim_next("worker-a")
    assert claimed is not None and claimed.id == job_id
    downloads: list[tuple[str, str | None]] = []

    def downloader(url: str, *, proxy: str | None = None) -> bytes:
        downloads.append((url, proxy))
        return png_bytes()

    handler = ImageJobHandler(
        queue=queue,
        media=media,
        output_root=tmp_path / "outputs",
        matsca_provider=lambda mode: FakeNativeMatscaProvider(),
        downloader=downloader,
        native_download_proxy="http://127.0.0.1:7890",
    )

    handler.handle(claimed, worker_id="worker-a")

    assert downloads == [
        ("https://official.example/image.png", "http://127.0.0.1:7890")
    ]
    assert queue.get(job_id).status == JobStatus.COMPLETED


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
            matsca_mode="native",
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


def test_image_handler_uses_async_task_for_direct_image_edit(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "workbench.db")
    initialize_database(engine)
    queue = JobQueue(engine)
    media = MediaRepository(engine)
    source_job = queue.enqueue("image.generate", {})
    source_path = tmp_path / "source.png"
    source_path.write_bytes(png_bytes())
    media_id = media.record_image(
        job_id=source_job,
        model="gpt-image-2",
        prompt="source",
        parameters={},
        path=source_path,
        thumbnail_path=source_path,
        width=64,
        height=32,
        sha256="hash",
    )
    queue.cancel(source_job)
    job_id = ImageJobService(queue).submit(
        ImageJobRequest(
            model="gpt-image-2",
            prompt="edit",
            matsca_mode="direct",
            input_media_ids=[media_id],
        )
    )
    claimed = queue.claim_next("worker-a")
    assert claimed is not None and claimed.id == job_id
    provider = FakeAsyncMatscaProvider()
    handler = ImageJobHandler(
        queue=queue,
        media=media,
        output_root=tmp_path / "outputs",
        matsca_provider=lambda mode: provider,
        async_poll_interval=0,
        async_poll_timeout=1,
    )

    handler.handle(claimed, worker_id="worker-a")

    stored = queue.get(job_id)
    assert stored.status == JobStatus.COMPLETED
    assert stored.payload["matsca_task_id"] == "task-edit-1"
    assert provider.client_task_id == f"image-video-{job_id}"
    assert not provider.edited_sync


def test_image_handler_rejects_single_input_over_ten_mb(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "workbench.db")
    initialize_database(engine)
    queue = JobQueue(engine)
    media = MediaRepository(engine)
    source_job = queue.enqueue("image.generate", {})
    source_path = tmp_path / "source-large.bin"
    source_path.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
    media_id = media.record_image(
        job_id=source_job,
        model="gpt-image-2",
        prompt="source",
        parameters={},
        path=source_path,
        thumbnail_path=source_path,
        width=64,
        height=32,
        sha256="hash",
    )
    queue.cancel(source_job)
    job_id = ImageJobService(queue).submit(
        ImageJobRequest(
            model="gpt-image-2",
            prompt="edit",
            matsca_mode="direct",
            input_media_ids=[media_id],
        )
    )
    claimed = queue.claim_next("worker-a")
    assert claimed is not None and claimed.id == job_id
    handler = ImageJobHandler(
        queue=queue,
        media=media,
        output_root=tmp_path / "outputs",
        matsca_provider=lambda mode: FakeAsyncMatscaProvider(),
    )

    with pytest.raises(ValueError, match="10 MB"):
        handler.handle(claimed, worker_id="worker-a")


def test_image_handler_rejects_total_input_over_eighty_mb() -> None:
    class Asset:
        def __init__(self, file_size_bytes: int):
            self.file_size_bytes = file_size_bytes

    assets = [Asset(10 * 1024 * 1024) for _ in range(8)] + [Asset(1)]

    with pytest.raises(ValueError, match="80 MB"):
        ImageJobHandler._validate_reference_assets(assets)


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
        downloader=fake_downloader,
    )

    handler.handle(claimed, worker_id="worker-a")

    assert queue.get(job_id).status == JobStatus.COMPLETED
    assert len(MediaRepository(engine).for_job(job_id)) == 1


def test_image_worker_does_not_persist_result_after_pause(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "workbench.db")
    initialize_database(engine)
    queue = JobQueue(engine)
    media = MediaRepository(engine)
    job_id = ImageJobService(queue).submit(
        ImageJobRequest(model="gpt-image-2", prompt="cat")
    )

    class PausingProvider(FakeMatscaProvider):
        def get_image_task(self, task_id: str) -> MatscaImageTask:
            assert task_id == "task-1"
            queue.pause(job_id)
            return MatscaImageTask(
                id="task-1",
                status="completed",
                images=[GeneratedImage(content=png_bytes())],
            )

    handler = ImageJobHandler(
        queue=queue,
        media=media,
        output_root=tmp_path / "outputs",
        matsca_provider=lambda mode: PausingProvider(),
    )
    runner = WorkerRunner(
        queue=queue,
        handlers={"image.generate": handler},
        worker_id="worker-a",
    )

    assert runner.run_once()

    assert queue.get(job_id).status == JobStatus.PAUSED
    assert media.for_job(job_id) == []
