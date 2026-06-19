"""DashScope Wan/Qwen multimodal image adapter."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, cast

import httpx

DASHSCOPE_ENDPOINT = (
    "https://dashscope.aliyuncs.com/api/v1/services/"
    "aigc/multimodal-generation/generation"
)


@dataclass(frozen=True)
class DashScopeResult:
    request_id: str
    image_urls: list[str]
    input_tokens: int
    width: int
    height: int
    raw: dict[str, Any]


class DashScopeProvider:
    def __init__(
        self,
        *,
        api_key: str,
        client: httpx.Client | None = None,
        timeout: float = 120,
    ):
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=timeout)

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def build_payload(
        self,
        *,
        model: str,
        params: dict[str, Any],
        input_images: list[bytes] | None = None,
    ) -> dict[str, Any]:
        content: list[dict[str, Any]] = []
        for image in input_images or []:
            encoded = base64.b64encode(image).decode()
            content.append({"image": f"data:image/png;base64,{encoded}"})
        text = params.get("text")
        if isinstance(text, str) and text:
            content.append({"text": text})
        allowed = {
            "n",
            "size",
            "negative_prompt",
            "thinking_mode",
            "prompt_extend",
            "watermark",
            "seed",
        }
        parameters = {
            key: value
            for key, value in params.items()
            if key in allowed and value is not None and value != ""
        }
        return {
            "model": model,
            "input": {"messages": [{"role": "user", "content": content}]},
            "parameters": parameters,
        }

    def generate(
        self,
        *,
        model: str,
        params: dict[str, Any],
        input_images: list[bytes] | None = None,
    ) -> DashScopeResult:
        response = self.client.post(
            DASHSCOPE_ENDPOINT,
            headers=self.headers,
            json=self.build_payload(
                model=model, params=params, input_images=input_images
            ),
        )
        response.raise_for_status()
        return self.parse_response(cast(dict[str, Any], response.json()))

    @staticmethod
    def parse_response(payload: dict[str, Any]) -> DashScopeResult:
        output = payload.get("output")
        output_dict = cast(dict[str, Any], output) if isinstance(output, dict) else {}
        urls: list[str] = []
        choices = output_dict.get("choices")
        if isinstance(choices, list):
            for choice_value in cast(list[object], choices):
                if not isinstance(choice_value, dict):
                    continue
                choice = cast(dict[str, Any], choice_value)
                message = choice.get("message")
                if not isinstance(message, dict):
                    continue
                content = cast(dict[str, Any], message).get("content")
                if not isinstance(content, list):
                    continue
                for item_value in cast(list[object], content):
                    if isinstance(item_value, dict):
                        image = cast(dict[str, Any], item_value).get("image")
                        if isinstance(image, str):
                            urls.append(image)
        usage_value = payload.get("usage")
        usage = (
            cast(dict[str, Any], usage_value)
            if isinstance(usage_value, dict)
            else {}
        )
        width = _integer(usage.get("width"))
        height = _integer(usage.get("height"))
        size = usage.get("size")
        if not width and not height and isinstance(size, str) and "*" in size:
            left, right = size.split("*", maxsplit=1)
            width, height = int(left), int(right)
        return DashScopeResult(
            request_id=str(payload.get("request_id") or ""),
            image_urls=urls,
            input_tokens=_integer(usage.get("input_tokens")),
            width=width,
            height=height,
            raw=payload,
        )


def _integer(value: object) -> int:
    return value if isinstance(value, int) else 0
