"""Initial evidence-first meeting schema.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])

    op.create_table(
        "meetings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("project_id", sa.String(length=200)),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("source_provider", sa.String(length=40), nullable=False),
        sa.Column("source_task_id", sa.String(length=200), unique=True),
        sa.Column("source_language", sa.String(length=40), nullable=False),
        sa.Column("audio_uri", sa.Text()),
        sa.Column("duration_ms", sa.BigInteger()),
        sa.Column("raw_result", postgresql.JSONB()),
        sa.Column("error", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    for column in ("tenant_id", "created_by", "project_id", "status", "created_at"):
        op.create_index(f"ix_meetings_{column}", "meetings", [column])

    op.create_table(
        "meeting_access",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "meeting_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.UniqueConstraint("meeting_id", "user_id", name="uq_meeting_access"),
    )
    op.create_index("ix_meeting_access_meeting_id", "meeting_access", ["meeting_id"])
    op.create_index("ix_meeting_access_user_id", "meeting_access", ["user_id"])

    op.create_table(
        "speakers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "meeting_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_speaker_id", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True)),
        sa.Column("identity_confidence", sa.Float()),
        sa.Column("identity_source", sa.String(length=60)),
        sa.UniqueConstraint(
            "meeting_id", "provider_speaker_id", name="uq_meeting_provider_speaker"
        ),
    )
    op.create_index("ix_speakers_meeting_id", "speakers", ["meeting_id"])
    op.create_index("ix_speakers_person_id", "speakers", ["person_id"])

    op.create_table(
        "segments",
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
        sa.Column(
            "speaker_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("speakers.id", ondelete="SET NULL"),
        ),
        sa.Column("paragraph_id", sa.String(length=200)),
        sa.Column("sentence_id", sa.Integer()),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.BigInteger(), nullable=False),
        sa.Column("end_ms", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("overlap", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("embedding", Vector(384)),
    )
    op.create_index("ix_segments_tenant_id", "segments", ["tenant_id"])
    op.create_index("ix_segments_meeting_id", "segments", ["meeting_id"])
    op.create_index("ix_segments_speaker_id", "segments", ["speaker_id"])
    op.create_index("ix_segments_meeting_start", "segments", ["meeting_id", "start_ms"])
    op.execute(
        "CREATE INDEX ix_segments_text_trgm ON segments USING gin (text gin_trgm_ops)"
    )

    op.create_table(
        "artifacts",
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
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("meeting_id", "kind", "version", name="uq_artifact_version"),
    )
    op.create_index("ix_artifacts_tenant_id", "artifacts", ["tenant_id"])
    op.create_index("ix_artifacts_meeting_id", "artifacts", ["meeting_id"])
    op.create_index("ix_artifacts_kind", "artifacts", ["kind"])

    op.create_table(
        "memory_records",
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
        sa.Column("project_id", sa.String(length=200)),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("subject", sa.String(length=500)),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True)),
        sa.Column("evidence_segment_ids", postgresql.JSONB(), nullable=False),
        sa.Column("extractor", postgresql.JSONB(), nullable=False),
        sa.Column("embedding", Vector(384)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    for column in ("tenant_id", "meeting_id", "project_id", "kind", "subject"):
        op.create_index(f"ix_memory_records_{column}", "memory_records", [column])

    op.create_table(
        "query_audits",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("scope", postgresql.JSONB(), nullable=False),
        sa.Column("response", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_query_audits_tenant_id", "query_audits", ["tenant_id"])
    op.create_index("ix_query_audits_user_id", "query_audits", ["user_id"])

    op.execute(
        """
        INSERT INTO tenants (id, name)
        VALUES ('00000000-0000-0000-0000-000000000001', 'Default Tenant')
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO users (id, tenant_id, display_name)
        VALUES (
          '00000000-0000-0000-0000-000000000001',
          '00000000-0000-0000-0000-000000000001',
          'Local Admin'
        )
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    for table in (
        "query_audits",
        "memory_records",
        "artifacts",
        "segments",
        "speakers",
        "meeting_access",
        "meetings",
        "users",
        "tenants",
    ):
        op.drop_table(table)

