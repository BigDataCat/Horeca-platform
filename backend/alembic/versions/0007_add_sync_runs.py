"""add sync run audit history

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-03
"""

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="running"),
        sa.Column("fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_duplicates", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["integration_id"], ["pos_integrations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_sync_runs_company_id", "sync_runs", ["company_id"])
    op.create_index("ix_sync_runs_integration_id", "sync_runs", ["integration_id"])


def downgrade() -> None:
    op.drop_index("ix_sync_runs_integration_id", table_name="sync_runs")
    op.drop_index("ix_sync_runs_company_id", table_name="sync_runs")
    op.drop_table("sync_runs")
