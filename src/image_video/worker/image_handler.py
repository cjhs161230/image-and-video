"""Worker handler for ordinary GPT-Image-2 jobs."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Protocol, cast

import httpx

from image_video.application.image_assets import ImageSaveError, save_image_atomic
from image_video.infrastructure.database.media import MediaRepository
from image_video.infrastructure.database.models import Job
from image_video.infrastructure.database.queue import JobQueue
from image_video.infrastructure.providers.dashscope import DashScopeResult
from image_video.infrastructure.providers.download import download_image
from image_video.infrastructure.providers.matsca import GeneratedImage, MatscaImageTask
from image_video.worker.errors import RecoverableImageRetrievalError


class MatscaImageProvider(Protocol):
    def task_slot(self) -> object: ...

    def generate(
        self,
        *,
        prompt: str,
        size: str,
        quality: str,
        style: str,
        n: int,
        background: str = "auto",
        moderation: str = "auto",
        output_format: str = "png",
        output_compression: int | None = None,
    ) -> list[GeneratedImage]: ...

    def edit(
        self,
        *,
        prompt: str,
        images: list[bytes],
        size: str,
        quality: str,
        moderation: str = "auto",
        output_format: str = "png",
        output_compression: int | None = None,
        input_fidelity: str | None = None,
    ) -> list[GeneratedImage]: ...

    def create_generation_task(
        self,
        *,
        prompt: str,
        size: str,
        quality: str,
        style: str,
        n: int,
        background: str = "auto",
        moderation: str = "auto",
        output_format: str = "png",
        output_compression: int | None = None,
        client_task_id: str | None = None,
    ) -> MatscaImageTask: ...

    def create_edit_task(
        self,
        *,
        prompt: str,
        images: list[bytes],
        size: str,
        quality: str,
        moderation: str = "auto",
        output_format: str = "png",
        output_compression: int | None = None,
        input_fidelity: str | None = None,
        client_task_id: str | None = None,
    ) -> MatscaImageTask: ...

    def get_image_task(self, task_id: str) -> MatscaImageTask: ...


class DashScopeImageProvider(Protocol):
    def generate(
        self,
        *,
        model: str,
        params: dict[str, Any],
        input_images: list[bytes] | None = None,
    ) -> DashScopeResult: ...


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
        async_poll_interval: float = 2,
        async_poll_timeout: float = 600,
    ):
        self.queue = queue
        self.media = media
        self.output_root = output_root
        self.matsca_provider = matsca_provider
        self.dashscope_provider = dashscope_provider
        self.downloader = downloader
        self.native_download_proxy = native_download_proxy
        self.async_poll_interval = async_poll_interval
        self.async_poll_timeout = async_poll_timeout

    def handle(self, job: Job, *, worker_id: str) -> None:
        payload = cast(dict[str, object], job.payload)
        model = str(payload["model"])
        self._ensure_client_task_id(job, worker_id, payload)
        result_urls = payload.get("result_urls")
        recovered_urls: list[str] = []
        if isinstance(result_urls, list):
            recovered_urls = [
                url for url in cast(list[object], result_urls) if isinstance(url, str)
            ]
        media_ids = cast(list[str], payload.get("input_media_ids", []))
        reference_assets = self.media.by_ids(media_ids)
        self._validate_reference_assets(reference_assets)
        reference_images = [Path(asset.path).read_bytes() for asset in reference_assets]
        if recovered_urls:
            images = [GeneratedImage(url=url) for url in recovered_urls]
        elif model == "gpt-image-2":
            self.queue.mark_upstream_request_sent(job.id, worker_id)
            matsca_mode = str(payload.get("matsca_mode", "direct"))
            provider = self.matsca_provider(matsca_mode)
            if reference_images and matsca_mode == "direct":
                images = self._edit_matsca_async(
                    job=job,
                    worker_id=worker_id,
                    provider=provider,
                    payload=payload,
                    reference_images=reference_images,
                )
            elif reference_images:
                images = provider.edit(
                    prompt=str(payload["prompt"]),
                    images=reference_images,
                    size=str(payload["size"]),
                    quality=str(payload["quality"]),
                    moderation=str(payload.get("moderation", "auto")),
                    output_format=str(payload["output_format"]),
                    output_compression=cast(
                        int | None, payload.get("output_compression")
                    ),
                    input_fidelity=cast(str | None, payload.get("input_fidelity")),
                )
            elif matsca_mode != "native":
                images = self._generate_matsca_async(
                    job=job,
                    worker_id=worker_id,
                    provider=provider,
                    payload=payload,
                )
            else:
                images = provider.generate(
                    prompt=str(payload["prompt"]),
                    size=str(payload["size"]),
                    quality=str(payload["quality"]),
                    style=str(payload["style"]),
                    n=int(cast(int, payload["n"])),
                    background=str(payload["background"]),
                    moderation=str(payload.get("moderation", "auto")),
                    output_format=str(payload["output_format"]),
                    output_compression=cast(
                        int | None, payload.get("output_compression")
                    ),
                )
        else:
            self.queue.mark_upstream_request_sent(job.id, worker_id)
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
        if not self.queue.is_running_by(job.id, worker_id):
            return
        directory = self.output_root / "images" / job.id
        directory.mkdir(parents=True, exist_ok=True)
        for index, generated in enumerate(images):
            content = generated.content
            if content is None and generated.url:
                self._persist_result_urls(job, worker_id, payload, images)
                if str(payload.get("matsca_mode", "")) == "native":
                    try:
                        content = self.downloader(
                            generated.url, proxy=self.native_download_proxy or None
                        )
                    except Exception as exc:
                        raise RecoverableImageRetrievalError(
                            error_code="IMAGE_DOWNLOAD_FAILED",
                            error_message=f"图片下载失败：{exc}",
                        ) from exc
                else:
                    try:
                        content = self.downloader(generated.url)
                    except Exception as exc:
                        raise RecoverableImageRetrievalError(
                            error_code="IMAGE_DOWNLOAD_FAILED",
                            error_message=f"图片下载失败：{exc}",
                        ) from exc
            if content is None:
                raise ValueError("图片结果没有可保存内容")
            extension = str(payload["output_format"])
            path = directory / f"image_{index:04d}.{extension}"
            thumbnail = directory / f"thumbnail_{index:04d}.jpg"
            try:
                saved = save_image_atomic(
                    content,
                    path,
                    thumbnail_path=thumbnail,
                )
            except ImageSaveError as exc:
                raise RecoverableImageRetrievalError(
                    error_code="IMAGE_SAVE_FAILED",
                    error_message=str(exc),
                ) from exc
            self.media.record_image(
                job_id=job.id,
                model=model,
                prompt=str(payload["prompt"]),
                parameters=payload,
                path=saved.path,
                thumbnail_path=saved.thumbnail_path or thumbnail,
                width=saved.width,
                height=saved.height,
                sha256=saved.sha256,
            )
        self.queue.complete(job.id, worker_id)

    def _ensure_client_task_id(
        self, job: Job, worker_id: str, payload: dict[str, object]
    ) -> str:
        client_task_id = payload.get("client_task_id")
        if isinstance(client_task_id, str) and client_task_id:
            return client_task_id
        client_task_id = f"image-video-{job.id}"
        self.queue.update_payload(job.id, worker_id, {"client_task_id": client_task_id})
        payload["client_task_id"] = client_task_id
        return client_task_id

    def _persist_result_urls(
        self,
        job: Job,
        worker_id: str,
        payload: dict[str, object],
        images: list[GeneratedImage],
    ) -> None:
        urls = [image.url for image in images if image.url]
        if not urls:
            return
        if payload.get("result_urls") == urls:
            return
        self.queue.update_payload(job.id, worker_id, {"result_urls": urls})
        payload["result_urls"] = urls

    def _generate_matsca_async(
        self,
        *,
        job: Job,
        worker_id: str,
        provider: MatscaImageProvider,
        payload: dict[str, object],
    ) -> list[GeneratedImage]:
        slot = getattr(provider, "task_slot", nullcontext)
        with slot():
            task_id = payload.get("matsca_task_id")
            if not isinstance(task_id, str) or not task_id:
                task = provider.create_generation_task(
                    client_task_id=str(payload["client_task_id"]),
                    prompt=str(payload["prompt"]),
                    size=str(payload["size"]),
                    quality=str(payload["quality"]),
                    style=str(payload["style"]),
                    n=int(cast(int, payload["n"])),
                    background=str(payload["background"]),
                    moderation=str(payload.get("moderation", "auto")),
                    output_format=str(payload["output_format"]),
                    output_compression=cast(
                        int | None, payload.get("output_compression")
                    ),
                )
                task_id = task.id
                self.queue.update_payload(job.id, worker_id, {"matsca_task_id": task_id})
            return self._poll_matsca_task(
                job=job,
                worker_id=worker_id,
                provider=provider,
                task_id=task_id,
            )

    def _edit_matsca_async(
        self,
        *,
        job: Job,
        worker_id: str,
        provider: MatscaImageProvider,
        payload: dict[str, object],
        reference_images: list[bytes],
    ) -> list[GeneratedImage]:
        slot = getattr(provider, "task_slot", nullcontext)
        with slot():
            task_id = payload.get("matsca_task_id")
            if not isinstance(task_id, str) or not task_id:
                task = provider.create_edit_task(
                    client_task_id=str(payload["client_task_id"]),
                    prompt=str(payload["prompt"]),
                    images=reference_images,
                    size=str(payload["size"]),
                    quality=str(payload["quality"]),
                    moderation=str(payload.get("moderation", "auto")),
                    output_format=str(payload["output_format"]),
                    output_compression=cast(
                        int | None, payload.get("output_compression")
                    ),
                    input_fidelity=cast(str | None, payload.get("input_fidelity")),
                )
                task_id = task.id
                self.queue.update_payload(job.id, worker_id, {"matsca_task_id": task_id})
            return self._poll_matsca_task(
                job=job,
                worker_id=worker_id,
                provider=provider,
                task_id=task_id,
            )

    def _poll_matsca_task(
        self,
        *,
        job: Job,
        worker_id: str,
        provider: MatscaImageProvider,
        task_id: str,
    ) -> list[GeneratedImage]:
        deadline = time.monotonic() + self.async_poll_timeout
        while True:
            task = provider.get_image_task(task_id)
            if task.status in {"completed", "succeeded", "success"} and task.images:
                return task.images
            if task.status in {"failed", "error", "cancelled"}:
                raise ValueError(task.error or f"Matsca 异步图片任务失败: {task.status}")
            if time.monotonic() >= deadline:
                raise httpx.ReadTimeout("Matsca 异步图片任务超时，结果状态不确定")
            if not self.queue.is_running_by(job.id, worker_id):
                return []
            time.sleep(self.async_poll_interval)

    @staticmethod
    def _validate_reference_assets(assets: Sequence[object]) -> None:
        max_single = 10 * 1024 * 1024
        max_total = 80 * 1024 * 1024
        total_size = sum(int(getattr(asset, "file_size_bytes", 0)) for asset in assets)
        if total_size > max_total:
            raise ValueError("输入图片总量不能超过 80 MB")
        for asset in assets:
            if int(getattr(asset, "file_size_bytes", 0)) > max_single:
                raise ValueError("单张输入图片不能超过 10 MB")
