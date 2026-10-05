"""location time zone

Revision ID: 0025
Revises: 0024
"""

from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("locations", sa.Column("timezone", sa.String(64), nullable=False, server_default="Europe/Bucharest"))


def downgrade() -> None:
    op.drop_column("locations", "timezone")
