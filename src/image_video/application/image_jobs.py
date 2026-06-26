"""Ordinary image job submission use case."""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from image_video.api.errors import BusinessValidationError
from image_video.infrastructure.database.queue import JobQueue

SUPPORTED_IMAGE_MODELS = {
    "wan2.7-image",
    "wan2.7-image-pro",
    "qwen-image-2.0",
    "qwen-image-2.0-pro",
    "gpt-image-2",
}


class ImageJobRequest(BaseModel):
    model: str
    prompt: str
    negative_prompt: str = ""
    n: int = 1
    size: str = "1024x1024"
    quality: Literal["auto", "low", "medium", "high"] = "medium"
    style: Literal["vivid", "natural"] = "vivid"
    background: Literal["auto", "transparent", "opaque"] = "auto"
    moderation: Literal["auto", "low"] = "auto"
    output_format: Literal["png", "jpeg", "webp"] = "png"
    output_compression: int | None = Field(default=None, ge=0, le=100)
    input_fidelity: Literal["low", "high"] | None = None
    matsca_mode: Literal["direct", "native"] = "direct"
    input_media_ids: list[str] = Field(default_factory=list)

    @field_validator("size", mode="before")
    @classmethod
    def normalize_size(cls, value: object) -> str:
        if value is None:
            return "auto"
        text = str(value).strip().lower()
        if not text or text == "auto":
            return "auto"
        if not re.fullmatch(r"[1-9]\d*x[1-9]\d*", text):
            raise ValueError("size 必须是 auto 或正整数宽高，如 1024x1024")
        return text

    @field_validator("quality", mode="before")
    @classmethod
    def normalize_quality_aliases(cls, value: object) -> str:
        if value == "standard":
            return "medium"
        if value == "hd":
            return "high"
        return str(value)


class ImageJobService:
    def __init__(self, queue: JobQueue):
        self.queue = queue

    def submit(self, request: ImageJobRequest) -> str:
        if request.model not in SUPPORTED_IMAGE_MODELS:
            raise BusinessValidationError(f"不支持的模型：{request.model}")
        if request.model == "gpt-image-2" and not 1 <= request.n <= 4:
            raise BusinessValidationError("GPT-Image-2 单次输出数量必须为 1 到 4")
        if request.model == "gpt-image-2" and len(request.input_media_ids) > 8:
            raise BusinessValidationError("GPT-Image-2 最多 8 张输入图片")
        return self.queue.enqueue("image.generate", request.model_dump())
