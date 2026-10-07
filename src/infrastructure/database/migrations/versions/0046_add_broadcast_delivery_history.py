from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0046"
down_revision: Union[str, None] = "0045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("broadcasts", sa.Column("campaign_id", sa.UUID(), nullable=True))
    # Previously created broadcasts have no reliable link to their old repeats.
    op.execute("UPDATE broadcasts SET campaign_id = task_id")
    op.alter_column("broadcasts", "campaign_id", nullable=False)
    op.create_index("ix_broadcasts_campaign_id", "broadcasts", ["campaign_id"])
    op.create_table(
        "broadcast_deliveries",
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("campaign_id", "telegram_id"),
    )
    op.execute(
        """
        INSERT INTO broadcast_deliveries (campaign_id, telegram_id)
        SELECT DISTINCT b.campaign_id, COALESCE(m.user_telegram_id, u.telegram_id)
        FROM broadcast_messages AS m
        JOIN broadcasts AS b ON b.id = m.broadcast_id
        JOIN users AS u ON u.id = m.user_id
        WHERE m.status IN ('SENT', 'EDITED', 'DELETED')
          AND b.status != 'DELETED'
          AND m.message_id IS NOT NULL
          AND COALESCE(m.user_telegram_id, u.telegram_id) IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("broadcast_deliveries")
    op.drop_index("ix_broadcasts_campaign_id", table_name="broadcasts")
    op.drop_column("broadcasts", "campaign_id")
