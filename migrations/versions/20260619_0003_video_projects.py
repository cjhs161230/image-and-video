"""Create video projects and storyboard versions.

Revision ID: 20260619_0003
Revises: 20260619_0002
Create Date: 2026-06-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260619_0003"
down_revision: str | None = "20260619_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "video_projects",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_video_projects_updated", "video_projects", ["updated_at"])
    op.create_table(
        "video_reference_images",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("video_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("media_id", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=20), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_video_reference_images_project",
        "video_reference_images",
        ["project_id", "position"],
    )
    op.create_table(
        "video_storyboard_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("video_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("suggestion", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_video_storyboard_versions_project",
        "video_storyboard_versions",
        ["project_id", "version"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_video_storyboard_versions_project",
        table_name="video_storyboard_versions",
    )
    op.drop_table("video_storyboard_versions")
    op.drop_index(
        "ix_video_reference_images_project",
        table_name="video_reference_images",
    )
    op.drop_table("video_reference_images")
    op.drop_index("ix_video_projects_updated", table_name="video_projects")
    op.drop_table("video_projects")
