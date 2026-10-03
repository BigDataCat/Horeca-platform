"""store webhook tokens as hashes outside the integration config

Revision ID: 0015
Revises: 0014
"""

import hashlib
import json

from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pos_integrations", sa.Column("webhook_token_hash", sa.String(64)))

    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, config FROM pos_integrations WHERE config IS NOT NULL")).all()
    for row_id, config in rows:
        if isinstance(config, str):
            config = json.loads(config)
        if not isinstance(config, dict) or "webhook_token" not in config:
            continue
        token = config.pop("webhook_token")
        digest = hashlib.sha256(str(token).encode()).hexdigest() if token else None
        connection.execute(
            sa.text("UPDATE pos_integrations SET webhook_token_hash = :h, config = :c WHERE id = :id"),
            {"h": digest, "c": json.dumps(config), "id": row_id},
        )


def downgrade() -> None:
    # Tokens cannot be recovered from their hashes; integrations need new ones after a downgrade.
    op.drop_column("pos_integrations", "webhook_token_hash")
