"""scheduled synchronisation settings and state

Revision ID: 0018
Revises: 0017
"""

from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pos_integrations", sa.Column("sync_interval_minutes", sa.Integer()))
    op.add_column("pos_integrations", sa.Column("next_sync_at", sa.DateTime(timezone=True)))
    op.add_column(
        "pos_integrations",
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("pos_integrations", sa.Column("sync_paused_reason", sa.String(500)))
    op.add_column("sync_runs", sa.Column("trigger", sa.String(20), nullable=False, server_default="manual"))
    op.create_index("ix_pos_integrations_next_sync_at", "pos_integrations", ["next_sync_at"])


def downgrade() -> None:
    op.drop_index("ix_pos_integrations_next_sync_at", table_name="pos_integrations")
    op.drop_column("sync_runs", "trigger")
    op.drop_column("pos_integrations", "sync_paused_reason")
    op.drop_column("pos_integrations", "consecutive_failures")
    op.drop_column("pos_integrations", "next_sync_at")
    op.drop_column("pos_integrations", "sync_interval_minutes")
