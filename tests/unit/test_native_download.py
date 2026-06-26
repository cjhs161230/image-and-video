import httpx
import pytest
import respx

from image_video.infrastructure.providers.download import download_image


@respx.mock
def test_download_image_uses_configured_proxy_transport_factory() -> None:
    used: list[str] = []

    def client_factory(proxy: str | None) -> httpx.Client:
        used.append(proxy or "")
        return httpx.Client()

    respx.get("https://cdn.test/image.png").mock(
        return_value=httpx.Response(
            200,
            headers={"Content-Type": "image/png"},
            content=b"image",
        )
    )

    content = download_image(
        "https://cdn.test/image.png",
        proxy="http://127.0.0.1:7890",
        client_factory=client_factory,
    )

    assert content == b"image"
    assert used == ["http://127.0.0.1:7890"]


@respx.mock
def test_download_image_requires_image_content_type() -> None:
    respx.get("https://cdn.test/error.html").mock(
        return_value=httpx.Response(200, headers={"Content-Type": "text/html"}, content=b"oops")
    )

    with pytest.raises(ValueError, match="图片下载失败.*Content-Type"):
        download_image("https://cdn.test/error.html")


@respx.mock
def test_download_image_rejects_empty_response() -> None:
    respx.get("https://cdn.test/empty.png").mock(
        return_value=httpx.Response(200, headers={"Content-Type": "image/png"}, content=b"")
    )

    with pytest.raises(ValueError, match="图片下载失败.*空"):
        download_image("https://cdn.test/empty.png")


@respx.mock
def test_download_image_rejects_oversized_response() -> None:
    respx.get("https://cdn.test/large.png").mock(
        return_value=httpx.Response(
            200,
            headers={"Content-Type": "image/png"},
            content=b"x" * 11,
        )
    )

    with pytest.raises(ValueError, match="图片下载失败.*大小"):
        download_image("https://cdn.test/large.png", max_bytes=10)


def test_download_image_supports_data_url() -> None:
    content = download_image("data:image/png;base64,aW1hZ2U=")

    assert content == b"image"


def test_download_image_rejects_invalid_url() -> None:
    with pytest.raises(ValueError, match="图片下载失败.*URL"):
        download_image("ftp://cdn.test/image.png")
