"""subscription expiry

Revision ID: 0026
Revises: 0025
"""

from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("plan_expires_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("companies", "plan_expires_at")
