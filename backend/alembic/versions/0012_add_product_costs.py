"""add product costs

Revision ID: 0012
Revises: 0011
"""

from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_costs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("locations.id", ondelete="CASCADE")),
        sa.Column("unit_cost", sa.Numeric(18, 6), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="RON"),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_product_costs_company_id", "product_costs", ["company_id"])
    op.create_index("ix_product_costs_product_id", "product_costs", ["product_id"])
    op.create_index("ix_product_costs_location_id", "product_costs", ["location_id"])


def downgrade() -> None:
    op.drop_table("product_costs")
