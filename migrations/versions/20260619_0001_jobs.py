"""Create persistent jobs and job events.

Revision ID: 20260619_0001
Revises:
Create Date: 2026-06-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260619_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("kind", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=15), nullable=False),
        sa.Column("locked_by", sa.String(length=100)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("upstream_request_sent", sa.Boolean(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=100)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_jobs_dispatch", "jobs", ["status", "created_at"])
    op.create_index("ix_jobs_lease", "jobs", ["status", "lease_expires_at"])
    op.create_table(
        "job_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.String(length=36),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event", sa.String(length=100), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_events_job_created", "job_events", ["job_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_job_events_job_created", table_name="job_events")
    op.drop_table("job_events")
    op.drop_index("ix_jobs_lease", table_name="jobs")
    op.drop_index("ix_jobs_dispatch", table_name="jobs")
    op.drop_table("jobs")

