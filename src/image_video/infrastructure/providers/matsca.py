"""Matsca OpenAI-compatible image provider."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from enum import StrEnum
from types import TracebackType
from typing import Any, cast
from uuid import uuid4

import httpx

from image_video.infrastructure.config import normalize_api_base_url
from image_video.infrastructure.providers.executor import CredentialGate, ProviderRequestExecutor


class ProviderConfigurationError(ValueError):
    pass


class UpstreamDirectUnavailableError(RuntimeError):
    pass


class MatscaMode(StrEnum):
    DIRECT = "direct"
    NATIVE = "native"


@dataclass(frozen=True)
class MatscaCredentials:
    mode: MatscaMode
    base_url: str
    api_key: str

    def validate(self) -> None:
        if not self.api_key:
            raise ProviderConfigurationError("Matsca API Key 未配置")


@dataclass(frozen=True)
class GeneratedImage:
    content: bytes | None = None
    url: str | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class MatscaImageTask:
    id: str
    status: str
    images: list[GeneratedImage]
    error: str = ""
    raw: dict[str, Any] | None = None


class MatscaProvider:
    def __init__(
        self,
        credentials: MatscaCredentials,
        *,
        timeout: float = 600,
        client: httpx.Client | None = None,
        task_gate: CredentialGate | None = None,
        request_executor: ProviderRequestExecutor | None = None,
    ):
        credentials.validate()
        self.credentials = credentials
        self.base_url = normalize_api_base_url(credentials.base_url)
        self.client = client or httpx.Client(timeout=timeout)
        self.task_gate = task_gate
        self.request_executor = request_executor

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.credentials.api_key}"}

    def task_slot(self) -> _TaskSlot:
        if self.credentials.mode != MatscaMode.DIRECT or self.task_gate is None:
            return _TaskSlot(nullcontext())
        return _TaskSlot(self.task_gate.slot())

    def _request_slot(self) -> _TaskSlot:
        if self.task_gate is None:
            return _TaskSlot(nullcontext())
        return _TaskSlot(self.task_gate.slot())

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
    ) -> list[GeneratedImage]:
        response_format = (
            "url" if self.credentials.mode == MatscaMode.NATIVE else "b64_json"
        )
        payload: dict[str, Any] = {
            "model": "gpt-image-2",
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "style": style,
            "n": n,
            "background": background,
            "moderation": moderation,
            "output_format": output_format,
            "response_format": response_format,
        }
        if output_compression is not None:
            payload["output_compression"] = output_compression
        with self._request_slot():
            response = self._send(
                lambda: self.client.post(
                    f"{self.base_url}/images/generations",
                    headers={**self.headers, "Content-Type": "application/json"},
                    json=payload,
                )
            )
        return self._parse_images(response.json())

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
    ) -> MatscaImageTask:
        if self.credentials.mode == MatscaMode.NATIVE:
            raise ValueError("原生模式必须使用同步图片接口获取官方图片 URL")
        payload: dict[str, Any] = {
            "client_task_id": client_task_id or f"image-video-{uuid4().hex}",
            "model": "gpt-image-2",
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "style": style,
            "n": n,
            "background": background,
            "moderation": moderation,
            "output_format": output_format,
            "response_format": "b64_json",
        }
        if output_compression is not None:
            payload["output_compression"] = output_compression
        with self._request_slot():
            response = self._send(
                lambda: self.client.post(
                    f"{self._task_base_url()}/api/image-tasks/generations",
                    headers={**self.headers, "Content-Type": "application/json"},
                    json=payload,
                )
            )
        return self._parse_task(response.json())

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
    ) -> MatscaImageTask:
        if self.credentials.mode == MatscaMode.NATIVE:
            raise ValueError("原生模式必须使用同步图片接口获取官方图片 URL")
        if not 1 <= len(images) <= 8:
            raise ValueError("图生图需要 1 到最多 8 张输入图片")
        files = [
            ("image", (f"reference-{index}.png", image, "image/png"))
            for index, image in enumerate(images)
        ]
        data: dict[str, str] = {
            "client_task_id": client_task_id or f"image-video-{uuid4().hex}",
            "model": "gpt-image-2",
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "moderation": moderation,
            "output_format": output_format,
            "response_format": "b64_json",
        }
        if output_compression is not None:
            data["output_compression"] = str(output_compression)
        if input_fidelity is not None:
            data["input_fidelity"] = input_fidelity
        with self._request_slot():
            response = self._send(
                lambda: self.client.post(
                    f"{self._task_base_url()}/api/image-tasks/edits",
                    headers=self.headers,
                    data=data,
                    files=files,
                )
            )
        return self._parse_task(response.json())

    def get_image_task(self, task_id: str) -> MatscaImageTask:
        with self._request_slot():
            response = self._send(
                lambda: self.client.get(
                    f"{self._task_base_url()}/api/image-tasks",
                    headers=self.headers,
                    params={"ids": task_id},
                )
            )
        payload = response.json()
        if isinstance(payload, dict):
            typed_payload = cast(dict[str, Any], payload)
            items = typed_payload.get("items")
            if not isinstance(items, list):
                raise ValueError("Matsca 异步图片任务列表响应缺少 items")
            for item in cast(list[object], items):
                if not isinstance(item, dict):
                    continue
                typed_item = cast(dict[str, Any], item)
                if typed_item.get("id") == task_id:
                    return self._parse_task(typed_item)
        raise ValueError("Matsca 异步图片任务不存在")

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
    ) -> list[GeneratedImage]:
        if not 1 <= len(images) <= 8:
            raise ValueError("图生图需要 1 到最多 8 张输入图片")
        files = [
            ("image", (f"reference-{index}.png", image, "image/png"))
            for index, image in enumerate(images)
        ]
        data: dict[str, str] = {
            "model": "gpt-image-2",
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "moderation": moderation,
            "output_format": output_format,
            "response_format": (
                "url" if self.credentials.mode == MatscaMode.NATIVE else "b64_json"
            ),
        }
        if output_compression is not None:
            data["output_compression"] = str(output_compression)
        if input_fidelity is not None:
            data["input_fidelity"] = input_fidelity
        with self._request_slot():
            response = self._send(
                lambda: self.client.post(
                    f"{self.base_url}/images/edits",
                    headers=self.headers,
                    data=data,
                    files=files,
                )
            )
        return self._parse_images(response.json())

    def _task_base_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return self.base_url[: -len("/v1")]
        return self.base_url

    def _send(self, operation: Callable[[], httpx.Response]) -> httpx.Response:
        def execute() -> httpx.Response:
            response = operation()
            response.raise_for_status()
            return response

        try:
            if self.request_executor is not None:
                return self.request_executor.run(execute)
            return execute()
        except httpx.HTTPStatusError as exc:
            if self._response_error_code(exc.response) == "upstream_direct_unavailable":
                raise UpstreamDirectUnavailableError(
                    "官方直连不可用 — 原生模式下官方 API 直连暂不可用"
                ) from exc
            raise

    @staticmethod
    def _response_error_code(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return ""
        if not isinstance(payload, dict):
            return ""
        typed_payload = cast(dict[str, Any], payload)
        error = typed_payload.get("error")
        if isinstance(error, dict):
            typed_error = cast(dict[str, Any], error)
            code = typed_error.get("code")
            if isinstance(code, str):
                return code
        code = typed_payload.get("code")
        return code if isinstance(code, str) else ""

    @staticmethod
    def _parse_images(payload: dict[str, Any]) -> list[GeneratedImage]:
        items = payload.get("data")
        if not isinstance(items, list):
            raise ValueError("Matsca 响应缺少 data 图片列表")
        results: list[GeneratedImage] = []
        for raw_item in cast(list[object], items):
            if not isinstance(raw_item, dict):
                continue
            item = cast(dict[str, Any], raw_item)
            encoded = item.get("b64_json")
            url = item.get("url")
            if isinstance(encoded, str):
                try:
                    content = base64.b64decode(encoded, validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise ValueError("Matsca 图片 base64 解码失败") from exc
                results.append(GeneratedImage(content=content, raw=item))
            elif isinstance(url, str):
                results.append(GeneratedImage(url=url, raw=item))
            else:
                raise ValueError("Matsca 图片结果缺少 b64_json/url")
        if not results:
            raise ValueError("Matsca 图片结果缺少 b64_json/url")
        return results

    @classmethod
    def _parse_task(cls, payload: dict[str, Any]) -> MatscaImageTask:
        task_id = payload.get("id") or payload.get("task_id")
        if not isinstance(task_id, str):
            raise ValueError("Matsca 异步图片任务响应缺少任务 ID")
        status = payload.get("status")
        if not isinstance(status, str):
            status = "unknown"
        images: list[GeneratedImage] = []
        result = payload.get("result")
        if isinstance(result, dict):
            images = cls._parse_images_for_task(cast(dict[str, Any], result), status)
        else:
            images = cls._parse_images_for_task(payload, status)
        error = payload.get("error") or payload.get("error_message") or ""
        return MatscaImageTask(
            id=task_id,
            status=status,
            images=images,
            error=str(error) if error else "",
            raw=payload,
        )

    @classmethod
    def _parse_images_if_present(cls, payload: dict[str, Any]) -> list[GeneratedImage]:
        try:
            return cls._parse_images(payload)
        except ValueError:
            return []

    @classmethod
    def _parse_images_for_task(
        cls, payload: dict[str, Any], status: str
    ) -> list[GeneratedImage]:
        if status in {"completed", "succeeded", "success"}:
            return cls._parse_images(payload)
        return cls._parse_images_if_present(payload)


class _TaskSlot:
    def __init__(self, context: Any):
        self._context = context

    def __enter__(self) -> None:
        self._context.__enter__()
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return self._context.__exit__(exc_type, exc, traceback)
