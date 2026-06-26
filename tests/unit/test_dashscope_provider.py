import base64

import httpx

from image_video.infrastructure.providers.dashscope import DashScopeProvider
from image_video.infrastructure.providers.executor import (
    CredentialGate,
    ProviderRequestExecutor,
)
from image_video.infrastructure.providers.limiter import AdaptiveLimiter


def test_dashscope_payload_keeps_each_image_and_text_as_separate_content_items() -> None:
    provider = DashScopeProvider(api_key="test-key")

    payload = provider.build_payload(
        model="qwen-image-2.0",
        params={"text": "combine", "n": 1, "size": "1024*1024"},
        input_images=[b"one", b"two"],
    )

    content = payload["input"]["messages"][0]["content"]
    assert content == [
        {"image": f"data:image/png;base64,{base64.b64encode(b'one').decode()}"},
        {"image": f"data:image/png;base64,{base64.b64encode(b'two').decode()}"},
        {"text": "combine"},
    ]
    assert payload["parameters"] == {"n": 1, "size": "1024*1024"}


def test_dashscope_response_extracts_images_and_dimensions() -> None:
    provider = DashScopeProvider(api_key="test-key")

    result = provider.parse_response(
        {
            "request_id": "req-1",
            "output": {
                "choices": [
                    {"message": {"content": [{"image": "https://cdn.test/image.png"}]}}
                ]
            },
            "usage": {"size": "1488*704", "input_tokens": 4},
        }
    )

    assert result.image_urls == ["https://cdn.test/image.png"]
    assert result.width == 1488
    assert result.height == 704


def test_dashscope_generate_uses_provider_request_executor() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "request_id": "req-1",
                "output": {
                    "choices": [
                        {
                            "message": {
                                "content": [{"image": "https://cdn.test/image.png"}]
                            }
                        }
                    ]
                },
                "usage": {"size": "1024*1024"},
            },
        )

    executor = ProviderRequestExecutor(
        gate=CredentialGate(AdaptiveLimiter(max_concurrency=1)),
        sleep=lambda _: None,
        jitter=lambda: 0,
    )
    executed: list[bool] = []
    original_run = executor.run

    def recording_run(operation, *, request_id: str = "provider"):
        executed.append(True)
        return original_run(operation, request_id=request_id)

    executor.run = recording_run
    provider = DashScopeProvider(
        api_key="test-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        request_executor=executor,
    )

    result = provider.generate(
        model="qwen-image-2.0",
        params={"text": "cat", "n": 1, "size": "1024*1024"},
    )

    assert result.request_id == "req-1"
    assert executed == [True]
    assert calls == [
        "/api/v1/services/aigc/multimodal-generation/generation"
    ]
