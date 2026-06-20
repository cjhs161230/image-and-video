"""Create video frames.

Revision ID: 20260619_0005
Revises: 20260619_0004
Create Date: 2026-06-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260619_0005"
down_revision: str | None = "20260619_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "video_frames",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("video_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("frame", sa.Integer(), nullable=False),
        sa.Column("segment_start_frame", sa.Integer(), nullable=False),
        sa.Column("segment_end_frame", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_video_frames_project_frame",
        "video_frames",
        ["project_id", "frame"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_video_frames_project_frame", table_name="video_frames")
    op.drop_table("video_frames")
