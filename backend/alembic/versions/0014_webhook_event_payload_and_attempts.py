"""store webhook payloads and attempts for replay

Revision ID: 0014
Revises: 0013
"""

from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("webhook_events", sa.Column("payload", sa.Text()))
    op.add_column("webhook_events", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("webhook_events", sa.Column("processed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("webhook_events", "processed_at")
    op.drop_column("webhook_events", "attempts")
    op.drop_column("webhook_events", "payload")
