"""add product mappings and uom conversions

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-03
"""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("external_product_id", sa.String(length=200), nullable=False),
        sa.Column("external_product_name", sa.String(length=300), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("match_method", sa.String(length=30), nullable=False, server_default="manual"),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="1"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["integration_id"], ["pos_integrations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("integration_id", "external_product_id", name="uq_product_mapping_integration_external"),
    )
    op.create_index("ix_product_mappings_company_id", "product_mappings", ["company_id"])
    op.create_index("ix_product_mappings_integration_id", "product_mappings", ["integration_id"])
    op.create_index("ix_product_mappings_product_id", "product_mappings", ["product_id"])

    op.create_table(
        "product_uom_conversions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("from_uom", sa.String(length=20), nullable=False),
        sa.Column("to_uom", sa.String(length=20), nullable=False),
        sa.Column("factor", sa.Numeric(14, 6), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("product_id", "from_uom", "to_uom", name="uq_product_uom_conversion"),
    )
    op.create_index("ix_product_uom_conversions_company_id", "product_uom_conversions", ["company_id"])
    op.create_index("ix_product_uom_conversions_product_id", "product_uom_conversions", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_product_uom_conversions_product_id", table_name="product_uom_conversions")
    op.drop_index("ix_product_uom_conversions_company_id", table_name="product_uom_conversions")
    op.drop_table("product_uom_conversions")
    op.drop_index("ix_product_mappings_product_id", table_name="product_mappings")
    op.drop_index("ix_product_mappings_integration_id", table_name="product_mappings")
    op.drop_index("ix_product_mappings_company_id", table_name="product_mappings")
    op.drop_table("product_mappings")
