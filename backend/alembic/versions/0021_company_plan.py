"""company subscription plan

Revision ID: 0021
Revises: 0020
"""

from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing companies keep generous limits; new ones get settings.default_plan.
    op.add_column("companies", sa.Column("plan", sa.String(30), nullable=False, server_default="business"))


def downgrade() -> None:
    op.drop_column("companies", "plan")
