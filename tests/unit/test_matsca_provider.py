import base64

import httpx
import pytest
import respx

from image_video.infrastructure.providers.matsca import (
    MatscaCredentials,
    MatscaMode,
    MatscaProvider,
    ProviderConfigurationError,
)


def make_provider(mode: MatscaMode = MatscaMode.DIRECT) -> MatscaProvider:
    return MatscaProvider(
        MatscaCredentials(
            mode=mode,
            base_url="https://img.matsca.com",
            api_key="test-key",
            app_id="app-id" if mode == MatscaMode.APP else "",
            app_secret="app-secret" if mode == MatscaMode.APP else "",
        )
    )


def test_app_mode_adds_application_headers() -> None:
    headers = make_provider(MatscaMode.APP).headers

    assert headers["Authorization"] == "Bearer test-key"
    assert headers["X-App-ID"] == "app-id"
    assert headers["X-App-Secret"] == "app-secret"


def test_app_mode_requires_app_credentials() -> None:
    with pytest.raises(ProviderConfigurationError):
        MatscaCredentials(
            mode=MatscaMode.APP,
            base_url="https://img.matsca.com/v1",
            api_key="test-key",
        ).validate()


@respx.mock
def test_generate_uses_base64_for_direct_mode() -> None:
    route = respx.post("https://img.matsca.com/v1/images/generations").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"b64_json": base64.b64encode(b"png").decode()}]},
        )
    )

    images = make_provider().generate(
        prompt="cat",
        size="1024x1024",
        quality="medium",
        style="natural",
        n=1,
    )

    assert images[0].content == b"png"
    assert route.calls[0].request.read()
    assert b'"response_format":"b64_json"' in route.calls[0].request.content


@respx.mock
def test_native_mode_returns_url_for_proxy_download_stage() -> None:
    respx.post("https://img.matsca.com/v1/images/generations").mock(
        return_value=httpx.Response(200, json={"data": [{"url": "https://cdn.test/image.png"}]})
    )

    images = make_provider(MatscaMode.NATIVE).generate(
        prompt="cat", size="1024x1024", quality="medium", style="vivid", n=1
    )

    assert images[0].url == "https://cdn.test/image.png"
    assert images[0].content is None


def test_edit_rejects_more_than_eight_input_images() -> None:
    with pytest.raises(ValueError, match="最多 8 张"):
        make_provider().edit(
            prompt="keep character",
            images=[b"x"] * 9,
            size="1024x1024",
            quality="medium",
        )

