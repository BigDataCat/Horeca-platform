"""add canonical products and sales

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-03
"""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(length=100), nullable=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("category", sa.String(length=150), nullable=True),
        sa.Column("base_uom", sa.String(length=20), nullable=False, server_default="EA"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_products_company_id", "products", ["company_id"])
    op.create_index("ix_products_sku", "products", ["sku"])

    op.create_table(
        "sales",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=True),
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("net_value", sa.Numeric(14, 2), nullable=False),
        sa.Column("tax_value", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("gross_value", sa.Numeric(14, 2), nullable=False),
        sa.Column("source_payload", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["integration_id"], ["pos_integrations.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_sales_company_id", "sales", ["company_id"])
    op.create_index("ix_sales_location_id", "sales", ["location_id"])
    op.create_index("ix_sales_integration_id", "sales", ["integration_id"])
    op.create_index("ix_sales_occurred_at", "sales", ["occurred_at"])

    op.create_table(
        "sale_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sale_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("external_product_id", sa.String(length=200), nullable=True),
        sa.Column("product_name", sa.String(length=300), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 4), nullable=False),
        sa.Column("uom", sa.String(length=20), nullable=False),
        sa.Column("unit_price", sa.Numeric(14, 4), nullable=False),
        sa.Column("net_value", sa.Numeric(14, 2), nullable=False),
        sa.Column("tax_value", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["sale_id"], ["sales.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_sale_lines_sale_id", "sale_lines", ["sale_id"])
    op.create_index("ix_sale_lines_product_id", "sale_lines", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_sale_lines_product_id", table_name="sale_lines")
    op.drop_index("ix_sale_lines_sale_id", table_name="sale_lines")
    op.drop_table("sale_lines")
    op.drop_index("ix_sales_occurred_at", table_name="sales")
    op.drop_index("ix_sales_integration_id", table_name="sales")
    op.drop_index("ix_sales_location_id", table_name="sales")
    op.drop_index("ix_sales_company_id", table_name="sales")
    op.drop_table("sales")
    op.drop_index("ix_products_sku", table_name="products")
    op.drop_index("ix_products_company_id", table_name="products")
    op.drop_table("products")
