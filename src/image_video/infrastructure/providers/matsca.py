"""Matsca OpenAI-compatible image provider."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast

import httpx

from image_video.infrastructure.config import normalize_api_base_url


class ProviderConfigurationError(ValueError):
    pass


class MatscaMode(StrEnum):
    APP = "app"
    DIRECT = "direct"
    NATIVE = "native"


@dataclass(frozen=True)
class MatscaCredentials:
    mode: MatscaMode
    base_url: str
    api_key: str
    app_id: str = ""
    app_secret: str = ""

    def validate(self) -> None:
        if not self.api_key:
            raise ProviderConfigurationError("Matsca API Key 未配置")
        if self.mode == MatscaMode.APP and not (self.app_id and self.app_secret):
            raise ProviderConfigurationError("应用模式需要 App ID 和 App Secret")


@dataclass(frozen=True)
class GeneratedImage:
    content: bytes | None = None
    url: str | None = None
    raw: dict[str, Any] | None = None


class MatscaProvider:
    def __init__(
        self,
        credentials: MatscaCredentials,
        *,
        timeout: float = 600,
        client: httpx.Client | None = None,
    ):
        credentials.validate()
        self.credentials = credentials
        self.base_url = normalize_api_base_url(credentials.base_url)
        self.client = client or httpx.Client(timeout=timeout)

    @property
    def headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.credentials.api_key}"}
        if self.credentials.mode == MatscaMode.APP:
            headers["X-App-ID"] = self.credentials.app_id
            headers["X-App-Secret"] = self.credentials.app_secret
        return headers

    def generate(
        self,
        *,
        prompt: str,
        size: str,
        quality: str,
        style: str,
        n: int,
        background: str = "auto",
        output_format: str = "png",
    ) -> list[GeneratedImage]:
        response_format = (
            "url" if self.credentials.mode == MatscaMode.NATIVE else "b64_json"
        )
        response = self.client.post(
            f"{self.base_url}/images/generations",
            headers={**self.headers, "Content-Type": "application/json"},
            json={
                "model": "gpt-image-2",
                "prompt": prompt,
                "size": size,
                "quality": quality,
                "style": style,
                "n": n,
                "background": background,
                "output_format": output_format,
                "response_format": response_format,
            },
        )
        response.raise_for_status()
        return self._parse_images(response.json())

    def edit(
        self,
        *,
        prompt: str,
        images: list[bytes],
        size: str,
        quality: str,
        output_format: str = "png",
    ) -> list[GeneratedImage]:
        if not 1 <= len(images) <= 8:
            raise ValueError("图生图需要 1 到最多 8 张输入图片")
        files = [
            ("image", (f"reference-{index}.png", image, "image/png"))
            for index, image in enumerate(images)
        ]
        response = self.client.post(
            f"{self.base_url}/images/edits",
            headers=self.headers,
            data={
                "model": "gpt-image-2",
                "prompt": prompt,
                "size": size,
                "quality": quality,
                "output_format": output_format,
                "response_format": (
                    "url"
                    if self.credentials.mode == MatscaMode.NATIVE
                    else "b64_json"
                ),
            },
            files=files,
        )
        response.raise_for_status()
        return self._parse_images(response.json())

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
                results.append(
                    GeneratedImage(content=base64.b64decode(encoded), raw=item)
                )
            elif isinstance(url, str):
                results.append(GeneratedImage(url=url, raw=item))
        if not results:
            raise ValueError("Matsca 响应未包含可用图片")
        return results
