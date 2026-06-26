"""Safe local image persistence helpers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError


class ImageSaveError(ValueError):
    pass


@dataclass(frozen=True)
class SavedImage:
    path: Path
    thumbnail_path: Path | None
    width: int
    height: int
    sha256: str


def save_image_atomic(
    content: bytes,
    path: Path,
    *,
    thumbnail_path: Path | None = None,
    validate_image: bool = True,
) -> SavedImage:
    if not content:
        raise ImageSaveError("图片保存失败：图片内容为空")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temp_path.write_bytes(content)
        if temp_path.stat().st_size <= 0:
            raise ImageSaveError("图片保存失败：临时文件为空")
        if validate_image:
            with Image.open(temp_path) as image:
                image.verify()
            with Image.open(temp_path) as image:
                width, height = image.size
        else:
            width = 0
            height = 0
        temp_path.replace(path)
        if path.stat().st_size <= 0:
            raise ImageSaveError("图片保存失败：正式文件为空")
        if thumbnail_path is not None:
            thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(path) as source:
                preview = source.convert("RGB")
                preview.thumbnail((512, 512))
                preview.save(thumbnail_path, format="JPEG", quality=85)
        return SavedImage(
            path=path,
            thumbnail_path=thumbnail_path,
            width=width,
            height=height,
            sha256=hashlib.sha256(content).hexdigest(),
        )
    except ImageSaveError:
        raise
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise ImageSaveError("图片保存失败：图片文件无法打开或校验失败") from exc
    finally:
        temp_path.unlink(missing_ok=True)
