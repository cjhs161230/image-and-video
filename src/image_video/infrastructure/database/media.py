"""Image generation and media asset persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from image_video.infrastructure.database.models import ImageGeneration, MediaAsset


class MediaRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    def record_image(
        self,
        *,
        job_id: str,
        model: str,
        prompt: str,
        parameters: dict[str, object],
        path: Path,
        thumbnail_path: Path,
        width: int,
        height: int,
        sha256: str,
    ) -> str:
        now = datetime.now(UTC)
        media_id = str(uuid4())
        with Session(self.engine) as session:
            generation = session.scalar(
                select(ImageGeneration).where(ImageGeneration.job_id == job_id)
            )
            if generation is None:
                session.add(
                    ImageGeneration(
                        job_id=job_id,
                        model=model,
                        prompt=prompt,
                        parameters=parameters,
                        created_at=now,
                    )
                )
            session.add(
                MediaAsset(
                    id=media_id,
                    job_id=job_id,
                    media_type="image",
                    path=str(path),
                    thumbnail_path=str(thumbnail_path),
                    width=width,
                    height=height,
                    file_size_bytes=path.stat().st_size,
                    sha256=sha256,
                    created_at=now,
                )
            )
            session.commit()
        return media_id

    def for_job(self, job_id: str) -> list[MediaAsset]:
        with Session(self.engine) as session:
            assets = list(
                session.scalars(
                    select(MediaAsset)
                    .where(MediaAsset.job_id == job_id)
                    .order_by(MediaAsset.created_at, MediaAsset.id)
                )
            )
            for asset in assets:
                session.expunge(asset)
            return assets

    def by_ids(self, media_ids: list[str]) -> list[MediaAsset]:
        if not media_ids:
            return []
        with Session(self.engine) as session:
            found = list(
                session.scalars(select(MediaAsset).where(MediaAsset.id.in_(media_ids)))
            )
            by_id = {asset.id: asset for asset in found}
            ordered = [by_id[media_id] for media_id in media_ids if media_id in by_id]
            for asset in ordered:
                session.expunge(asset)
            return ordered
