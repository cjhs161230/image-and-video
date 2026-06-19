import httpx
import respx

from image_video.infrastructure.providers.download import download_image


@respx.mock
def test_download_image_uses_configured_proxy_transport_factory() -> None:
    used: list[str] = []

    def client_factory(proxy: str | None) -> httpx.Client:
        used.append(proxy or "")
        return httpx.Client()

    respx.get("https://cdn.test/image.png").mock(
        return_value=httpx.Response(200, content=b"image")
    )

    content = download_image(
        "https://cdn.test/image.png",
        proxy="http://127.0.0.1:7890",
        client_factory=client_factory,
    )

    assert content == b"image"
    assert used == ["http://127.0.0.1:7890"]

