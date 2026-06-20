"""Worker handler for ordinary GPT-Image-2 jobs."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

from PIL import Image

from image_video.infrastructure.database.media import MediaRepository
from image_video.infrastructure.database.models import Job
from image_video.infrastructure.database.queue import JobQueue
from image_video.infrastructure.providers.dashscope import DashScopeResult
from image_video.infrastructure.providers.download import download_image
from image_video.infrastructure.providers.matsca import GeneratedImage


class MatscaImageProvider(Protocol):
    def generate(self, **kwargs: object) -> list[GeneratedImage]: ...

    def edit(self, **kwargs: object) -> list[GeneratedImage]: ...


class DashScopeImageProvider(Protocol):
    def generate(self, **kwargs: object) -> DashScopeResult: ...


class ImageJobHandler:
    def __init__(
        self,
        *,
        queue: JobQueue,
        media: MediaRepository,
        output_root: Path,
        matsca_provider: Callable[[str], MatscaImageProvider],
        dashscope_provider: Callable[[], DashScopeImageProvider] | None = None,
        downloader: Callable[..., bytes] = download_image,
        native_download_proxy: str = "",
    ):
        self.queue = queue
        self.media = media
        self.output_root = output_root
        self.matsca_provider = matsca_provider
        self.dashscope_provider = dashscope_provider
        self.downloader = downloader
        self.native_download_proxy = native_download_proxy

    def handle(self, job: Job, *, worker_id: str) -> None:
        payload = cast(dict[str, object], job.payload)
        model = str(payload["model"])
        self.queue.mark_upstream_request_sent(job.id, worker_id)
        media_ids = cast(list[str], payload.get("input_media_ids", []))
        reference_images = [
            Path(asset.path).read_bytes() for asset in self.media.by_ids(media_ids)
        ]
        if model == "gpt-image-2":
            provider = self.matsca_provider(str(payload.get("matsca_mode", "direct")))
            if reference_images:
                images = provider.edit(
                    prompt=str(payload["prompt"]),
                    images=reference_images,
                    size=str(payload["size"]),
                    quality=str(payload["quality"]),
                    output_format=str(payload["output_format"]),
                )
            else:
                images = provider.generate(
                    prompt=str(payload["prompt"]),
                    size=str(payload["size"]),
                    quality=str(payload["quality"]),
                    style=str(payload["style"]),
                    n=int(cast(int, payload["n"])),
                    background=str(payload["background"]),
                    output_format=str(payload["output_format"]),
                )
        else:
            if self.dashscope_provider is None:
                raise ValueError("DashScope Provider 未配置")
            result = self.dashscope_provider().generate(
                model=model,
                params={
                    "text": str(payload["prompt"]),
                    "negative_prompt": str(payload.get("negative_prompt", "")),
                    "n": int(cast(int, payload["n"])),
                    "size": str(payload["size"]).replace("x", "*"),
                },
                input_images=reference_images,
            )
            images = [GeneratedImage(url=url) for url in result.image_urls]
        directory = self.output_root / "images" / job.id
        directory.mkdir(parents=True, exist_ok=True)
        for index, generated in enumerate(images):
            content = generated.content
            if content is None and generated.url:
                if str(payload.get("matsca_mode", "")) == "native":
                    content = self.downloader(
                        generated.url, proxy=self.native_download_proxy or None
                    )
                else:
                    content = self.downloader(generated.url)
            if content is None:
                raise ValueError("图片结果没有可保存内容")
            extension = str(payload["output_format"])
            path = directory / f"image_{index:04d}.{extension}"
            path.write_bytes(content)
            thumbnail = directory / f"thumbnail_{index:04d}.jpg"
            with Image.open(path) as source:
                width, height = source.size
                preview = source.convert("RGB")
                preview.thumbnail((512, 512))
                preview.save(thumbnail, format="JPEG", quality=85)
            self.media.record_image(
                job_id=job.id,
                model=model,
                prompt=str(payload["prompt"]),
                parameters=payload,
                path=path,
                thumbnail_path=thumbnail,
                width=width,
                height=height,
                sha256=hashlib.sha256(content).hexdigest(),
            )
        self.queue.complete(job.id, worker_id)
