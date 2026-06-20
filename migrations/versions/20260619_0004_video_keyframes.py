"""Create video keyframes.

Revision ID: 20260619_0004
Revises: 20260619_0003
Create Date: 2026-06-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260619_0004"
down_revision: str | None = "20260619_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "video_keyframes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("video_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "storyboard_version_id",
            sa.String(length=36),
            sa.ForeignKey("video_storyboard_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("frame", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_video_keyframes_project_frame",
        "video_keyframes",
        ["project_id", "frame"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_video_keyframes_project_frame", table_name="video_keyframes")
    op.drop_table("video_keyframes")
