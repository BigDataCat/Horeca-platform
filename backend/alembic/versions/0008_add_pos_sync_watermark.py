"""add POS sync watermark

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-03
"""

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pos_integrations", sa.Column("last_sync_cursor", sa.String(length=500), nullable=True))
    op.add_column("pos_integrations", sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("pos_integrations", "last_synced_at")
    op.drop_column("pos_integrations", "last_sync_cursor")
