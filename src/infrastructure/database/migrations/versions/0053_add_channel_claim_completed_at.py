"""Record the time of successful channel task completion."""

import sqlalchemy as sa
from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("channel_claims", sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.execute(
        sa.text("UPDATE channel_claims SET completed_at = updated_at WHERE status = 'completed'")
    )
    op.create_index(
        "ix_channel_claims_completed_at",
        "channel_claims",
        ["completed_at"],
        postgresql_where=sa.text("status = 'completed'"),
    )


def downgrade() -> None:
    op.drop_index("ix_channel_claims_completed_at", table_name="channel_claims")
    op.drop_column("channel_claims", "completed_at")
