"""DeepSeek storyboard planning and review adapter."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, Field

from image_video.infrastructure.config import normalize_api_base_url


class StoryboardKeyframe(BaseModel):
    frame: int = Field(ge=0)
    description: str
    prompt: str


class StoryboardSegment(BaseModel):
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    motion: str


class StoryboardPlan(BaseModel):
    global_prompt: str
    character_lock: str
    scene_lock: str
    camera_lock: str
    keyframes: list[StoryboardKeyframe] = Field(min_length=1)
    segments: list[StoryboardSegment]


class DeepSeekPlanner:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        sleep: Callable[[float], None] = time.sleep,
        client: httpx.Client | None = None,
    ):
        self.api_key = api_key
        self.base_url = normalize_api_base_url(base_url)
        self.model = model
        self.sleep = sleep
        self.client = client or httpx.Client(timeout=120)

    def create_storyboard(self, request: dict[str, Any]) -> StoryboardPlan:
        response = self._post_with_retry(
            {
                "model": self.model,
                "temperature": 0.3,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
                ],
            }
        )
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        return StoryboardPlan.model_validate_json(content)

    def _post_with_retry(self, payload: dict[str, Any]) -> httpx.Response:
        last_response: httpx.Response | None = None
        for attempt in range(3):
            response = self.client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            last_response = response
            if response.status_code < 500 and response.status_code != 429:
                response.raise_for_status()
                return response
            if attempt < 2:
                self.sleep(2**attempt)
        if last_response is None:
            raise RuntimeError("DeepSeek request was not attempted")
        last_response.raise_for_status()
        raise RuntimeError("unreachable")

    @staticmethod
    def _system_prompt() -> str:
        return (
            "你是视频分镜规划器。只输出严格 JSON。必须包含 global_prompt、"
            "character_lock、scene_lock、camera_lock、keyframes 和 segments。"
            "keyframes 包含 frame、description、prompt；segments 包含 "
            "start_frame、end_frame、motion。"
        )
