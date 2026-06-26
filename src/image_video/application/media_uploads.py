"""Local user-uploaded image persistence service."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from image_video.api.errors import BusinessValidationError
from image_video.domain.jobs import JobStatus
from image_video.infrastructure.database.media import MediaRepository
from image_video.infrastructure.database.models import Job

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
FORMAT_TO_SUFFIX = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}


class MediaUploadService:
    def __init__(self, engine: Engine, media_repository: MediaRepository, *, data_root: Path):
        self.engine = engine
        self.media_repository = media_repository
        self.data_root = data_root

    def save_uploaded_image(self, *, filename: str, content: bytes) -> dict[str, object]:
        if not content:
            raise BusinessValidationError("上传文件不能为空")
        if len(content) > MAX_UPLOAD_BYTES:
            raise BusinessValidationError("单张上传图片不能超过 10 MB")

        try:
            image: Image.Image = Image.open(BytesIO(content))
            image.load()  # pyright: ignore[reportUnknownMemberType]
        except Exception as exc:  # pragma: no cover
            raise BusinessValidationError("上传文件不是有效图片") from exc

        format_name = (image.format or "").upper()
        suffix = FORMAT_TO_SUFFIX.get(format_name)
        if suffix is None:
            raise BusinessValidationError("仅支持 PNG、JPEG 或 WebP 图片上传")

        job_id = str(uuid4())
        upload_dir = self.data_root / "uploads" / job_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        original_path = upload_dir / f"original{suffix}"
        thumbnail_path = upload_dir / "thumbnail.jpg"
        original_path.write_bytes(content)

        preview = image.copy()
        if preview.mode not in {"RGB", "L"}:
            preview = preview.convert("RGB")
        preview.thumbnail((512, 512))
        preview.save(thumbnail_path, format="JPEG", quality=85)

        now = datetime.now(UTC)
        with Session(self.engine) as session:
            session.add(
                Job(
                    id=job_id,
                    kind="media.upload",
                    payload={"filename": filename or original_path.name},
                    status=JobStatus.COMPLETED,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()

        media_id = self.media_repository.record_image(
            job_id=job_id,
            model="user-upload",
            prompt=filename or "uploaded image",
            parameters={"source": "upload", "filename": filename},
            path=original_path,
            thumbnail_path=thumbnail_path,
            width=image.width,
            height=image.height,
            sha256=sha256(content).hexdigest(),
        )
        return {
            "media_id": media_id,
            "url": f"/api/v1/media/{media_id}",
            "width": image.width,
            "height": image.height,
        }
