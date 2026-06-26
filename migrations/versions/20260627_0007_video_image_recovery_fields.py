"""Add video image recovery metadata.

Revision ID: 20260627_0007
Revises: 20260622_0006
Create Date: 2026-06-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260627_0007"
down_revision: str | None = "20260622_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "video_keyframes",
        sa.Column("client_task_id", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "video_keyframes",
        sa.Column("result_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "video_frames",
        sa.Column("client_task_id", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "video_frames",
        sa.Column("result_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("video_frames", "result_url")
    op.drop_column("video_frames", "client_task_id")
    op.drop_column("video_keyframes", "result_url")
    op.drop_column("video_keyframes", "client_task_id")
