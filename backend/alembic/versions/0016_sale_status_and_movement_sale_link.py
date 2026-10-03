"""sale status and stock movement to sale link

Revision ID: 0016
Revises: 0015
"""

from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sales", sa.Column("status", sa.String(20), nullable=False, server_default="completed"))
    op.add_column("sales", sa.Column("status_reason", sa.String(500)))
    op.add_column("sales", sa.Column("status_changed_at", sa.DateTime(timezone=True)))
    op.add_column(
        "stock_movements",
        sa.Column("sale_id", sa.Integer(), sa.ForeignKey("sales.id", ondelete="SET NULL")),
    )
    op.create_index("ix_stock_movements_sale_id", "stock_movements", ["sale_id"])
    # Backfill: consumption movements referenced the external sale id at the sale's location.
    op.execute(
        """
        UPDATE stock_movements m
        SET sale_id = s.id
        FROM sales s
        WHERE m.reference_type = 'sale'
          AND m.sale_id IS NULL
          AND s.company_id = m.company_id
          AND s.location_id = m.location_id
          AND s.external_id = m.reference_id
          AND (SELECT count(*) FROM sales s2
               WHERE s2.company_id = m.company_id
                 AND s2.location_id = m.location_id
                 AND s2.external_id = m.reference_id) = 1
        """
    )


def downgrade() -> None:
    op.drop_index("ix_stock_movements_sale_id", table_name="stock_movements")
    op.drop_column("stock_movements", "sale_id")
    op.drop_column("sales", "status_changed_at")
    op.drop_column("sales", "status_reason")
    op.drop_column("sales", "status")
