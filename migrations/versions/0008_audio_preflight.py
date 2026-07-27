"""Add direct uploads and durable audio preflight metadata.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("meetings", sa.Column("normalized_audio_uri", sa.Text()))
    op.add_column("meetings", sa.Column("audio_input_hash", sa.String(length=64)))
    op.add_column("meetings", sa.Column("audio_preflight", postgresql.JSONB()))
    op.add_column(
        "meetings", sa.Column("audio_preprocess_version", sa.String(length=80))
    )
    op.add_column(
        "meetings",
        sa.Column(
            "denoise_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index("ix_meetings_audio_input_hash", "meetings", ["audio_input_hash"])

    op.create_table(
        "upload_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "meeting_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("meetings.id", ondelete="SET NULL"),
        ),
        sa.Column("object_name", sa.Text(), nullable=False, unique=True),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=200), nullable=False),
        sa.Column("expected_size", sa.BigInteger(), nullable=False),
        sa.Column("expected_sha256", sa.String(length=64)),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("project_id", sa.String(length=200)),
        sa.Column("source_language", sa.String(length=40), nullable=False),
        sa.Column(
            "denoise_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    for column in ("tenant_id", "user_id", "meeting_id", "status"):
        op.create_index(f"ix_upload_sessions_{column}", "upload_sessions", [column])


def downgrade() -> None:
    op.drop_table("upload_sessions")
    op.drop_index("ix_meetings_audio_input_hash", table_name="meetings")
    for column in (
        "denoise_enabled",
        "audio_preprocess_version",
        "audio_preflight",
        "audio_input_hash",
        "normalized_audio_uri",
    ):
        op.drop_column("meetings", column)
