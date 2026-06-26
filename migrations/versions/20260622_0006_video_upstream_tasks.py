"""Add recoverable upstream task IDs to video images.

Revision ID: 20260622_0006
Revises: 20260619_0005
Create Date: 2026-06-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260622_0006"
down_revision: str | None = "20260619_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "video_keyframes",
        sa.Column("upstream_task_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "video_frames",
        sa.Column("upstream_task_id", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("video_frames", "upstream_task_id")
    op.drop_column("video_keyframes", "upstream_task_id")
