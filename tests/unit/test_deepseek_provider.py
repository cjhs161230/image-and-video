import httpx
import respx

from image_video.infrastructure.providers.deepseek import DeepSeekPlanner
from image_video.infrastructure.providers.executor import (
    CredentialGate,
    ProviderRequestExecutor,
)
from image_video.infrastructure.providers.limiter import AdaptiveLimiter


@respx.mock
def test_deepseek_returns_validated_storyboard() -> None:
    respx.post("https://api.deepseek.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"global_prompt":"same scene","character_lock":"hero",'
                                '"scene_lock":"street","camera_lock":"wide",'
                                '"keyframes":[{"frame":0,"description":"start","prompt":"start"},'
                                '{"frame":11,"description":"end","prompt":"end"}],'
                                '"segments":[{"start_frame":0,"end_frame":11,'
                                '"motion":"turn head"}]}'
                            )
                        }
                    }
                ]
            },
        )
    )
    planner = DeepSeekPlanner(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        sleep=lambda _: None,
    )

    plan = planner.create_storyboard({"description": "turn", "total_frames": 12})

    assert len(plan.keyframes) == 2
    assert plan.segments[0].motion == "turn head"


@respx.mock
def test_deepseek_retries_server_errors_three_total_attempts() -> None:
    route = respx.post("https://api.deepseek.com/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(500, text="one"),
            httpx.Response(502, text="two"),
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"global_prompt":"","character_lock":"","scene_lock":"",'
                                    '"camera_lock":"","keyframes":[{"frame":0,'
                                    '"description":"start","prompt":"start"}],'
                                    '"segments":[]}'
                                )
                            }
                        }
                    ]
                },
            ),
        ]
    )
    planner = DeepSeekPlanner(
        api_key="test-key",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
        sleep=lambda _: None,
    )

    planner.create_storyboard({"description": "start", "total_frames": 1})

    assert route.call_count == 3


@respx.mock
def test_deepseek_uses_provider_request_executor() -> None:
    route = respx.post("https://api.deepseek.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"global_prompt":"","character_lock":"","scene_lock":"",'
                                '"camera_lock":"","keyframes":[{"frame":0,'
                                '"description":"start","prompt":"start"}],'
                                '"segments":[]}'
                            )
                        }
                    }
                ]
            },
        )
    )
    executor = ProviderRequestExecutor(
        gate=CredentialGate(AdaptiveLimiter(max_concurrency=1)),
        sleep=lambda _: None,
        jitter=lambda: 0,
    )
    planner = DeepSeekPlanner(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        sleep=lambda _: None,
        request_executor=executor,
    )

    planner.create_storyboard({"description": "start", "total_frames": 1})

    assert route.call_count == 1


@respx.mock
def test_deepseek_reviews_existing_storyboard_with_separate_request() -> None:
    route = respx.post("https://api.deepseek.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"global_prompt":"reviewed","character_lock":"hero",'
                                '"scene_lock":"street","camera_lock":"wide",'
                                '"keyframes":[{"frame":0,"description":"start",'
                                '"prompt":"improved"}],"segments":[]}'
                            )
                        }
                    }
                ]
            },
        )
    )
    planner = DeepSeekPlanner(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        sleep=lambda _: None,
    )

    reviewed = planner.review_storyboard(
        {
            "project": {"title": "demo", "total_frames": 1},
            "storyboard": {
                "global_prompt": "original",
                "character_lock": "hero",
                "scene_lock": "street",
                "camera_lock": "wide",
                "keyframes": [
                    {"frame": 0, "description": "start", "prompt": "start"}
                ],
                "segments": [],
            },
        }
    )

    assert reviewed.global_prompt == "reviewed"
    sent = route.calls[0].request.content.decode()
    assert "视频分镜复审器" in sent
    assert "original" in sent
