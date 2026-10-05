"""partial refunds: refunded amounts on sales and lines, stock movement to sale line link

Revision ID: 0023
Revises: 0022
"""

from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    zero = sa.text("0")
    op.add_column("sale_lines", sa.Column("refunded_quantity", sa.Numeric(14, 4), nullable=False, server_default=zero))
    op.add_column("sale_lines", sa.Column("refunded_net_value", sa.Numeric(14, 2), nullable=False, server_default=zero))
    op.add_column("sale_lines", sa.Column("refunded_tax_value", sa.Numeric(14, 2), nullable=False, server_default=zero))
    op.add_column("sales", sa.Column("refunded_net_value", sa.Numeric(14, 2), nullable=False, server_default=zero))
    op.add_column("sales", sa.Column("refunded_tax_value", sa.Numeric(14, 2), nullable=False, server_default=zero))
    op.add_column(
        "stock_movements",
        sa.Column("sale_line_id", sa.Integer(), sa.ForeignKey("sale_lines.id", ondelete="SET NULL")),
    )
    op.create_index("ix_stock_movements_sale_line_id", "stock_movements", ["sale_line_id"])
    # Sales cancelled/refunded before this migration keep their full values as refunded.
    op.execute("UPDATE sales SET refunded_net_value = net_value, refunded_tax_value = tax_value WHERE status IN ('cancelled','refunded')")


def downgrade() -> None:
    op.drop_index("ix_stock_movements_sale_line_id", table_name="stock_movements")
    op.drop_column("stock_movements", "sale_line_id")
    op.drop_column("sales", "refunded_tax_value")
    op.drop_column("sales", "refunded_net_value")
    op.drop_column("sale_lines", "refunded_tax_value")
    op.drop_column("sale_lines", "refunded_net_value")
    op.drop_column("sale_lines", "refunded_quantity")
