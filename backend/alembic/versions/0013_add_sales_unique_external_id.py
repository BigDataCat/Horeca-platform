"""enforce unique external sale id per integration

Revision ID: 0013
Revises: 0012
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fails if duplicate (integration_id, external_id) rows already exist;
    # de-duplicate them before upgrading an environment that has imported data.
    op.create_unique_constraint(
        "uq_sales_integration_external_id", "sales", ["integration_id", "external_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_sales_integration_external_id", "sales", type_="unique")
