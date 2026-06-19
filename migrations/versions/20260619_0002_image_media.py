"""Create image generations and media assets.

Revision ID: 20260619_0002
Revises: 20260619_0001
Create Date: 2026-06-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260619_0002"
down_revision: str | None = "20260619_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "image_generations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.String(length=36),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "media_assets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(length=36),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("media_type", sa.String(length=30), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("thumbnail_path", sa.Text(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_media_assets_job", "media_assets", ["job_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_media_assets_job", table_name="media_assets")
    op.drop_table("media_assets")
    op.drop_table("image_generations")

