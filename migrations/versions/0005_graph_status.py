"""Track durable graph projection state.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "meetings",
        sa.Column(
            "graph_status",
            sa.String(length=40),
            nullable=False,
            server_default="PENDING",
        ),
    )
    op.add_column(
        "meetings",
        sa.Column("graph_indexed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_meetings_graph_status", "meetings", ["graph_status"])


def downgrade() -> None:
    op.drop_index("ix_meetings_graph_status", table_name="meetings")
    op.drop_column("meetings", "graph_indexed_at")
    op.drop_column("meetings", "graph_status")
