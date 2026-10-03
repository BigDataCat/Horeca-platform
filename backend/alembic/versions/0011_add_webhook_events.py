"""add webhook events

Revision ID: 0011
Revises: 0010
"""

from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("integration_id", sa.Integer(), sa.ForeignKey("pos_integrations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_event_id", sa.String(200), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="received"),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_webhook_events_company_id", "webhook_events", ["company_id"])
    op.create_index("ix_webhook_events_integration_id", "webhook_events", ["integration_id"])
    op.create_unique_constraint(
        "uq_webhook_events_integration_event",
        "webhook_events",
        ["integration_id", "external_event_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_webhook_events_integration_event", "webhook_events", type_="unique")
    op.drop_table("webhook_events")
