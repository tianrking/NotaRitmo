"""Track Temporal pipeline runs and independently retryable stages.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "meeting_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workflow_id", sa.String(length=255), unique=True, nullable=False),
        sa.Column("workflow_run_id", sa.String(length=255)),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    for column in ("tenant_id", "meeting_id", "status"):
        op.create_index(f"ix_pipeline_runs_{column}", "pipeline_runs", [column])

    op.create_table(
        "pipeline_stages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "pipeline_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output", postgresql.JSONB(), nullable=False),
        sa.Column("error", postgresql.JSONB()),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "pipeline_run_id", "stage", name="uq_pipeline_run_stage"
        ),
    )
    for column in ("pipeline_run_id", "stage", "status"):
        op.create_index(f"ix_pipeline_stages_{column}", "pipeline_stages", [column])


def downgrade() -> None:
    op.drop_table("pipeline_stages")
    op.drop_table("pipeline_runs")
