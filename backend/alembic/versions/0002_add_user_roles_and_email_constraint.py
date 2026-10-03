"""add user roles and company email constraint

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-03
"""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=30), nullable=False, server_default="employee"),
    )
    op.create_unique_constraint(
        "uq_users_company_email",
        "users",
        ["company_id", "email"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_users_company_email", "users", type_="unique")
    op.drop_column("users", "role")
