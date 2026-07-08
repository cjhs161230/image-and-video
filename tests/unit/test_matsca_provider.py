import base64
import json
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from image_video.infrastructure.logging import JsonlLogger
from image_video.infrastructure.providers.executor import CredentialGate, ProviderRequestExecutor
from image_video.infrastructure.providers.limiter import AdaptiveLimiter
from image_video.infrastructure.providers.matsca import (
    MatscaCredentials,
    MatscaMode,
    MatscaProvider,
    ProviderConfigurationError,
    UpstreamDirectUnavailableError,
)


def request_json(request: httpx.Request) -> dict[str, Any]:
    payload = request.read()
    return httpx.Response(200, content=payload).json()


def make_provider(mode: MatscaMode = MatscaMode.DIRECT) -> MatscaProvider:
    return MatscaProvider(
        MatscaCredentials(
            mode=mode,
            base_url="https://img.matsca.com",
            api_key="test-key",
        )
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_only_direct_and_native_modes_are_supported() -> None:
    assert list(MatscaMode) == [MatscaMode.DIRECT, MatscaMode.NATIVE]
    assert make_provider().headers == {"Authorization": "Bearer test-key"}


@pytest.mark.parametrize(
    "base_url",
    [
        "img.matsca.com/v1",
        "ftp://img.matsca.com/v1",
        f"https://img.matsca.com/{'a' * 2100}",
    ],
)
def test_provider_rejects_invalid_base_url_before_request(base_url: str) -> None:
    with pytest.raises(ProviderConfigurationError, match="API Base URL"):
        MatscaProvider(
            MatscaCredentials(
                mode=MatscaMode.NATIVE,
                base_url=base_url,
                api_key="test-key",
            )
        )


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
        moderation="low",
        output_compression=55,
    )

    request = route.calls[0].request
    payload = request_json(request)
    assert images[0].content == b"png"
    assert request.url == "https://img.matsca.com/v1/images/generations"
    assert request.headers["authorization"] == "Bearer test-key"
    assert request.headers["content-type"] == "application/json"
    assert payload == {
        "model": "gpt-image-2",
        "prompt": "cat",
        "size": "1024x1024",
        "quality": "medium",
        "style": "natural",
        "n": 1,
        "background": "auto",
        "moderation": "low",
        "output_format": "png",
        "response_format": "b64_json",
        "output_compression": 55,
    }


@respx.mock
def test_native_mode_requests_base64_for_generation_success_rate() -> None:
    route = respx.post("https://img.matsca.com/v1/images/generations").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"b64_json": base64.b64encode(b"native-png").decode()}]},
        )
    )

    images = make_provider(MatscaMode.NATIVE).generate(
        prompt="cat", size="1024x1024", quality="medium", style="vivid", n=1
    )

    request = route.calls[0].request
    payload = request_json(request)
    assert images[0].content == b"native-png"
    assert images[0].url is None
    assert request.url == "https://img.matsca.com/v1/images/generations"
    assert request.headers["authorization"] == "Bearer test-key"
    assert request.headers["content-type"] == "application/json"
    assert payload == {
        "model": "gpt-image-2",
        "prompt": "cat",
        "size": "1024x1024",
        "quality": "medium",
        "style": "vivid",
        "n": 1,
        "background": "auto",
        "moderation": "auto",
        "output_image_format": "png",
        "response_format": "b64_json",
    }


@respx.mock
def test_direct_generation_accepts_url_result_even_when_requesting_base64() -> None:
    respx.post("https://img.matsca.com/v1/images/generations").mock(
        return_value=httpx.Response(200, json={"data": [{"url": "https://cdn.test/image.png"}]})
    )

    images = make_provider().generate(
        prompt="cat", size="1024x1024", quality="medium", style="natural", n=1
    )

    assert images[0].url == "https://cdn.test/image.png"
    assert images[0].content is None


@respx.mock
def test_native_generation_still_accepts_url_result() -> None:
    respx.post("https://img.matsca.com/v1/images/generations").mock(
        return_value=httpx.Response(200, json={"data": [{"url": "https://cdn.test/image.png"}]})
    )

    images = make_provider(MatscaMode.NATIVE).generate(
        prompt="cat", size="1024x1024", quality="medium", style="natural", n=1
    )

    assert images[0].url == "https://cdn.test/image.png"
    assert images[0].content is None


@respx.mock
def test_completed_direct_task_accepts_url_result() -> None:
    respx.get("https://img.matsca.com/api/image-tasks").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "task-url",
                        "status": "completed",
                        "result": {"data": [{"url": "https://cdn.test/task.png"}]},
                    }
                ]
            },
        )
    )

    task = make_provider().get_image_task("task-url")

    assert task.images[0].url == "https://cdn.test/task.png"
    assert task.images[0].content is None


@respx.mock
def test_image_result_without_base64_or_url_has_clear_error() -> None:
    respx.post("https://img.matsca.com/v1/images/generations").mock(
        return_value=httpx.Response(200, json={"data": [{"revised_prompt": "cat"}]})
    )

    with pytest.raises(ValueError, match="缺少 b64_json/url"):
        make_provider().generate(
            prompt="cat", size="1024x1024", quality="medium", style="natural", n=1
        )


@respx.mock
def test_invalid_base64_has_clear_error() -> None:
    respx.post("https://img.matsca.com/v1/images/generations").mock(
        return_value=httpx.Response(200, json={"data": [{"b64_json": "not-base64!"}]})
    )

    with pytest.raises(ValueError, match="base64 解码失败"):
        make_provider().generate(
            prompt="cat", size="1024x1024", quality="medium", style="natural", n=1
        )


@respx.mock
def test_native_edit_uses_sync_endpoint_and_requests_base64() -> None:
    route = respx.post("https://img.matsca.com/v1/images/edits").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"b64_json": base64.b64encode(b"edited").decode()}]},
        )
    )

    images = make_provider(MatscaMode.NATIVE).edit(
        prompt="keep character",
        images=[b"source"],
        size="1024x1024",
        quality="high",
        output_format="png",
        input_fidelity="high",
    )

    request = route.calls[0].request
    content = request.content
    assert images[0].content == b"edited"
    assert images[0].url is None
    assert request.url == "https://img.matsca.com/v1/images/edits"
    assert request.headers["authorization"] == "Bearer test-key"
    assert b'name="image"; filename="reference-0.png"' in content
    assert b'name="model"' in content
    assert b"gpt-image-2" in content
    assert b'name="prompt"' in content
    assert b"keep character" in content
    assert b'name="size"' in content
    assert b"1024x1024" in content
    assert b'name="quality"' in content
    assert b"high" in content
    assert b'name="moderation"' in content
    assert b"auto" in content
    assert b'name="output_image_format"' in content
    assert b"png" in content
    assert b'name="response_format"' in content
    assert b"b64_json" in content
    assert b'name="input_fidelity"' in content


def test_edit_rejects_more_than_eight_input_images() -> None:
    with pytest.raises(ValueError, match="最多 8 张"):
        make_provider().edit(
            prompt="keep character",
            images=[b"x"] * 9,
            size="1024x1024",
            quality="medium",
        )


@respx.mock
def test_create_generation_task_uses_direct_async_endpoint() -> None:
    route = respx.post("https://img.matsca.com/api/image-tasks/generations").mock(
        return_value=httpx.Response(200, json={"id": "task-1", "status": "queued"})
    )

    task = make_provider().create_generation_task(
        client_task_id="client-task-1",
        prompt="cat",
        size="1024x1024",
        quality="low",
        style="natural",
        n=1,
        output_format="png",
        output_compression=80,
    )

    request = route.calls[0].request
    payload = request_json(request)
    assert task.id == "task-1"
    assert task.status == "queued"
    assert request.url == "https://img.matsca.com/api/image-tasks/generations"
    assert request.headers["authorization"] == "Bearer test-key"
    assert request.headers["content-type"] == "application/json"
    assert payload == {
        "client_task_id": "client-task-1",
        "model": "gpt-image-2",
        "prompt": "cat",
        "size": "1024x1024",
        "quality": "low",
        "style": "natural",
        "n": 1,
        "background": "auto",
        "moderation": "auto",
        "output_format": "png",
        "response_format": "b64_json",
        "output_compression": 80,
    }


def test_native_mode_rejects_async_image_tasks() -> None:
    with pytest.raises(ValueError, match="原生模式"):
        make_provider(MatscaMode.NATIVE).create_generation_task(
            client_task_id="client-task-1",
            prompt="cat",
            size="1024x1024",
            quality="low",
            style="natural",
            n=1,
            output_format="png",
        )


@respx.mock
def test_create_edit_task_uses_direct_async_endpoint() -> None:
    route = respx.post("https://img.matsca.com/api/image-tasks/edits").mock(
        return_value=httpx.Response(200, json={"id": "task-edit-1", "status": "queued"})
    )

    task = make_provider().create_edit_task(
        client_task_id="client-edit-1",
        prompt="keep character",
        images=[b"one", b"two"],
        size="1024x1024",
        quality="high",
        output_format="png",
        moderation="low",
        output_compression=70,
        input_fidelity="high",
    )

    request = route.calls[0].request
    content = request.content
    assert task.id == "task-edit-1"
    assert request.url == "https://img.matsca.com/api/image-tasks/edits"
    assert request.headers["authorization"] == "Bearer test-key"
    assert content.count(b'name="image"; filename=') == 2
    assert b'name="image"; filename="reference-0.png"' in content
    assert b'name="image"; filename="reference-1.png"' in content
    assert b'name="client_task_id"' in content
    assert b"client-edit-1" in content
    assert b'name="model"' in content
    assert b"gpt-image-2" in content
    assert b'name="prompt"' in content
    assert b"keep character" in content
    assert b'name="size"' in content
    assert b"1024x1024" in content
    assert b'name="quality"' in content
    assert b"high" in content
    assert b'name="moderation"' in content
    assert b"low" in content
    assert b'name="output_format"' in content
    assert b"png" in content
    assert b'name="output_compression"' in content
    assert b"70" in content
    assert b'name="input_fidelity"' in content
    assert b'name="response_format"' in content
    assert b"b64_json" in content


@respx.mock
def test_get_image_task_parses_completed_direct_result() -> None:
    route = respx.get("https://img.matsca.com/api/image-tasks").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "task-1",
                        "status": "completed",
                        "result": {
                            "data": [
                                {"b64_json": base64.b64encode(b"png").decode()}
                            ]
                        },
                    }
                ],
                "total": 1,
                "has_more": False,
                "missing_ids": [],
            },
        )
    )

    task = make_provider().get_image_task("task-1")

    assert task.id == "task-1"
    assert task.status == "completed"
    assert task.images[0].content == b"png"
    request = route.calls[0].request
    assert request.url == "https://img.matsca.com/api/image-tasks?ids=task-1"
    assert request.headers["authorization"] == "Bearer test-key"


def test_direct_providers_share_same_per_key_concurrency_gate() -> None:
    gate = CredentialGate(AdaptiveLimiter(max_concurrency=2, current_limit=2))
    ordinary_provider = MatscaProvider(
        MatscaCredentials(
            mode=MatscaMode.DIRECT,
            base_url="https://img.matsca.com",
            api_key="shared-key",
        ),
        task_gate=gate,
    )
    keyframe_provider = MatscaProvider(
        MatscaCredentials(
            mode=MatscaMode.DIRECT,
            base_url="https://img.matsca.com",
            api_key="shared-key",
        ),
        task_gate=gate,
    )
    frame_provider = MatscaProvider(
        MatscaCredentials(
            mode=MatscaMode.DIRECT,
            base_url="https://img.matsca.com",
            api_key="shared-key",
        ),
        task_gate=gate,
    )
    first_entered = threading.Event()
    second_entered = threading.Event()
    third_entered = threading.Event()
    release_gate = threading.Event()

    def hold_slot(provider: MatscaProvider, entered: threading.Event) -> None:
        with provider.task_slot():
            entered.set()
            release_gate.wait(timeout=2)

    first = threading.Thread(target=hold_slot, args=(ordinary_provider, first_entered))
    second = threading.Thread(target=hold_slot, args=(keyframe_provider, second_entered))
    third = threading.Thread(target=hold_slot, args=(frame_provider, third_entered))
    first.start()
    second.start()
    third.start()

    assert first_entered.wait(timeout=2)
    assert second_entered.wait(timeout=2)
    assert not third_entered.wait(timeout=0.1)
    release_gate.set()
    assert third_entered.wait(timeout=2)
    first.join(timeout=2)
    second.join(timeout=2)
    third.join(timeout=2)


@respx.mock
def test_provider_executor_is_used_for_retry_after_in_real_matsca_requests() -> None:
    route = respx.post("https://img.matsca.com/v1/images/generations").mock(
        side_effect=[
            httpx.Response(
                429,
                headers={"Retry-After": "3"},
                request=httpx.Request("POST", "https://img.matsca.com/v1/images/generations"),
            ),
            httpx.Response(
                200,
                json={"data": [{"b64_json": base64.b64encode(b"png").decode()}]},
            ),
        ]
    )
    sleeps: list[float] = []
    provider = MatscaProvider(
        MatscaCredentials(
            mode=MatscaMode.DIRECT,
            base_url="https://img.matsca.com",
            api_key="test-key",
        ),
        request_executor=ProviderRequestExecutor(
            gate=CredentialGate(AdaptiveLimiter(max_concurrency=2, current_limit=2)),
            sleep=sleeps.append,
            jitter=lambda: 0,
        ),
    )

    images = provider.generate(
        prompt="cat",
        size="1024x1024",
        quality="medium",
        style="natural",
        n=1,
    )

    assert images[0].content == b"png"
    assert len(route.calls) == 2
    assert 3 in sleeps


@respx.mock
def test_provider_raises_upstream_direct_unavailable_error() -> None:
    respx.post("https://img.matsca.com/v1/images/generations").mock(
        return_value=httpx.Response(
            503,
            json={
                "error": {
                    "code": "upstream_direct_unavailable",
                    "message": "native unavailable",
                }
            },
        )
    )
    provider = MatscaProvider(
        MatscaCredentials(
            mode=MatscaMode.NATIVE,
            base_url="https://img.matsca.com",
            api_key="test-key",
        ),
        request_executor=ProviderRequestExecutor(
            gate=CredentialGate(AdaptiveLimiter(max_concurrency=2, current_limit=2)),
            sleep=lambda _: None,
            jitter=lambda: 0,
        ),
    )

    with pytest.raises(UpstreamDirectUnavailableError):
        provider.generate(
            prompt="cat",
            size="1024x1024",
            quality="medium",
            style="natural",
            n=1,
        )


@respx.mock
def test_native_generation_logs_started_and_succeeded_without_sensitive_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    route = respx.post("https://img.matsca.com/v1/images/generations").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"url": "https://cdn.test/image.png"}]},
        )
    )
    log_path = tmp_path / "provider.jsonl"
    provider = MatscaProvider(
        MatscaCredentials(
            mode=MatscaMode.NATIVE,
            base_url="https://img.matsca.com",
            api_key="test-key",
        ),
        request_executor=ProviderRequestExecutor(
            gate=CredentialGate(AdaptiveLimiter(max_concurrency=2, current_limit=2)),
            sleep=lambda _: None,
            jitter=lambda: 0,
            logger=JsonlLogger(log_path),
            provider="matsca.native",
        ),
    )

    provider.generate(
        request_id="job-native-1",
        prompt="secret prompt must not be logged",
        size="1024x1024",
        quality="medium",
        style="vivid",
        n=1,
    )

    assert route.called
    records = read_jsonl(log_path)
    assert [record["event"] for record in records] == [
        "provider_request_started",
        "provider_request_succeeded",
    ]
    for record in records:
        assert record["request_id"] == "job-native-1"
        data = record["data"]
        assert data["provider"] == "matsca.native"
        assert data["mode"] == "native"
        assert data["operation"] == "image.generate"
        assert data["endpoint_path"] == "/v1/images/generations"
        assert data["base_host"] == "img.matsca.com"
        assert data["response_format"] == "b64_json"
        assert data["attempt"] == 1
        assert data["system_proxy_env_present"] is True
        assert "HTTPS_PROXY" in data["system_proxy_env_keys"]
        assert data["native_download_proxy_configured"] is False
        assert data["vpn_detectable"] is False
    assert records[1]["data"]["http_status"] == 200
    assert isinstance(records[1]["data"]["elapsed_ms"], int)
    serialized = "\n".join(json.dumps(record, ensure_ascii=False) for record in records)
    assert "test-key" not in serialized
    assert "Bearer" not in serialized
    assert "secret prompt" not in serialized
    assert "https://cdn.test/image.png" not in serialized


@respx.mock
def test_native_generation_logs_remote_protocol_failure(
    tmp_path: Path,
) -> None:
    respx.post("https://img.matsca.com/v1/images/generations").mock(
        side_effect=httpx.RemoteProtocolError(
            "Server disconnected without sending a response."
        )
    )
    log_path = tmp_path / "provider.jsonl"
    provider = MatscaProvider(
        MatscaCredentials(
            mode=MatscaMode.NATIVE,
            base_url="https://img.matsca.com",
            api_key="test-key",
        ),
        request_executor=ProviderRequestExecutor(
            gate=CredentialGate(AdaptiveLimiter(max_concurrency=2, current_limit=2)),
            sleep=lambda _: None,
            jitter=lambda: 0,
            logger=JsonlLogger(log_path),
            provider="matsca.native",
        ),
    )

    with pytest.raises(httpx.RemoteProtocolError):
        provider.generate(
            request_id="job-native-failed",
            prompt="cat",
            size="1024x1024",
            quality="medium",
            style="vivid",
            n=1,
        )

    records = read_jsonl(log_path)
    assert [record["event"] for record in records] == [
        "provider_request_started",
        "provider_request_failed",
    ]
    failure = records[1]
    assert failure["request_id"] == "job-native-failed"
    assert failure["data"]["operation"] == "image.generate"
    assert failure["data"]["exception_type"] == "RemoteProtocolError"
    assert (
        failure["data"]["error_message"]
        == "Server disconnected without sending a response."
    )
    assert isinstance(failure["data"]["elapsed_ms"], int)
