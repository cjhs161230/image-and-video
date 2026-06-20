"""Ordinary image job submission use case."""

from typing import Literal

from pydantic import BaseModel, Field

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
    output_format: Literal["png", "jpeg", "webp"] = "png"
    matsca_mode: Literal["app", "direct", "native"] = "direct"
    input_media_ids: list[str] = Field(default_factory=list)


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
