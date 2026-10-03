"""add POS integration layer

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-03
"""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pos_integrations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("connection_type", sa.String(length=30), nullable=False, server_default="api"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="inactive"),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("external_account_id", sa.String(length=200), nullable=True),
        sa.Column("credentials_ref", sa.String(length=500), nullable=True),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_pos_integrations_company_id", "pos_integrations", ["company_id"])
    op.create_index("ix_pos_integrations_location_id", "pos_integrations", ["location_id"])


def downgrade() -> None:
    op.drop_index("ix_pos_integrations_location_id", table_name="pos_integrations")
    op.drop_index("ix_pos_integrations_company_id", table_name="pos_integrations")
    op.drop_table("pos_integrations")
