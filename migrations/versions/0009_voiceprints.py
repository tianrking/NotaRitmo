"""Add tenant-isolated people, voiceprints, samples and match candidates.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "people",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "display_name", name="uq_people_tenant_name"),
    )
    op.create_index("ix_people_tenant_id", "people", ["tenant_id"])
    op.create_index("ix_people_created_by", "people", ["created_by"])

    op.create_table(
        "voiceprint_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("people.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_version", sa.String(length=120), nullable=False),
        sa.Column("embedding", Vector(192), nullable=False),
        sa.Column("enrollment_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "tenant_id", "person_id", "model_version", name="uq_voiceprint_person_model"
        ),
    )
    for column in ("tenant_id", "person_id", "model_version"):
        op.create_index(
            f"ix_voiceprint_profiles_{column}", "voiceprint_profiles", [column]
        )

    op.create_table(
        "voiceprint_samples",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("voiceprint_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "meeting_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "speaker_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("speakers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("intervals", postgresql.JSONB(), nullable=False),
        sa.Column("embedding", Vector(192), nullable=False),
        sa.Column("duration_ms", sa.BigInteger(), nullable=False),
        sa.Column("quality", postgresql.JSONB(), nullable=False),
        sa.Column("audio_hash", sa.String(length=64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    for column in ("tenant_id", "profile_id", "meeting_id", "speaker_id"):
        op.create_index(
            f"ix_voiceprint_samples_{column}", "voiceprint_samples", [column]
        )

    op.create_table(
        "speaker_match_candidates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "speaker_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("speakers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("voiceprint_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("people.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("model_version", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "speaker_id", "profile_id", name="uq_speaker_match_profile"
        ),
    )
    for column in ("tenant_id", "speaker_id", "profile_id", "person_id", "status"):
        op.create_index(
            f"ix_speaker_match_candidates_{column}",
            "speaker_match_candidates",
            [column],
        )


def downgrade() -> None:
    op.drop_table("speaker_match_candidates")
    op.drop_table("voiceprint_samples")
    op.drop_table("voiceprint_profiles")
    op.drop_table("people")
