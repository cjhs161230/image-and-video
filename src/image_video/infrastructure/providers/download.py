"""Remote image download with an optional native-mode proxy."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from urllib.parse import urlparse

import httpx

ClientFactory = Callable[[str | None], httpx.Client]
DEFAULT_MAX_BYTES = 50 * 1024 * 1024


class ImageDownloadError(ValueError):
    pass


def default_client_factory(proxy: str | None) -> httpx.Client:
    return httpx.Client(proxy=proxy, timeout=120)


def download_image(
    url: str,
    *,
    proxy: str | None = None,
    client_factory: ClientFactory = default_client_factory,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> bytes:
    if not url.strip():
        raise ImageDownloadError("图片下载失败：URL 为空")
    normalized_url = url.strip()
    if normalized_url.startswith("data:"):
        return _decode_data_url(normalized_url, max_bytes=max_bytes)

    parsed = urlparse(normalized_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ImageDownloadError("图片下载失败：URL 必须是 http/https 或 data:image")

    try:
        with client_factory(proxy) as client:
            response = client.get(normalized_url)
            if not 200 <= response.status_code < 300:
                raise ImageDownloadError(
                    f"图片下载失败：HTTP 状态码 {response.status_code}"
                )
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
            if not content_type.startswith("image/"):
                raise ImageDownloadError(
                    f"图片下载失败：Content-Type 不是图片 ({content_type or 'missing'})"
                )
            content = response.content
    except ImageDownloadError:
        raise
    except httpx.TimeoutException as exc:
        raise ImageDownloadError("图片下载失败：请求超时") from exc
    except httpx.HTTPError as exc:
        raise ImageDownloadError("图片下载失败：网络请求异常") from exc

    return _validate_downloaded_bytes(content, max_bytes=max_bytes)


def _decode_data_url(url: str, *, max_bytes: int) -> bytes:
    header, separator, encoded = url.partition(",")
    if separator != ",":
        raise ImageDownloadError("图片下载失败：data URL 格式无效")
    media_type = header[5:].split(";", 1)[0].strip().lower()
    if not media_type.startswith("image/"):
        raise ImageDownloadError("图片下载失败：data URL Content-Type 不是图片")
    if ";base64" not in header.lower():
        raise ImageDownloadError("图片下载失败：data URL 必须使用 base64")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ImageDownloadError("图片下载失败：data URL base64 解码失败") from exc
    return _validate_downloaded_bytes(content, max_bytes=max_bytes)


def _validate_downloaded_bytes(content: bytes, *, max_bytes: int) -> bytes:
    if not content:
        raise ImageDownloadError("图片下载失败：响应内容为空")
    if len(content) > max_bytes:
        raise ImageDownloadError("图片下载失败：响应内容大小超过限制")
    return content
