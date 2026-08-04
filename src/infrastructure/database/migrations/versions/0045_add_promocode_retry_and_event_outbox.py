from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: Union[str, None] = "0044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "promocode_activations",
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "promocode_activations",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "promocode_activations",
        sa.Column("event_status", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "promocode_activations",
        sa.Column("event_attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "promocode_activations",
        sa.Column("event_next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "promocode_activations",
        sa.Column("event_last_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "promocode_activations",
        sa.Column("event_sent_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.drop_index(
        "uq_promocode_activations_pending_user",
        table_name="promocode_activations",
    )
    op.create_index(
        "uq_promocode_activations_pending_user",
        "promocode_activations",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('PENDING', 'FAILED', 'REQUIRES_REVIEW')"
        ),
    )
    op.create_index(
        "ix_promocode_activations_retry_due",
        "promocode_activations",
        ["status", "next_retry_at"],
        unique=False,
    )
    op.create_index(
        "ix_promocode_activations_event_due",
        "promocode_activations",
        ["event_status", "event_next_retry_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_promocode_activations_event_due",
        table_name="promocode_activations",
    )
    op.drop_index(
        "ix_promocode_activations_retry_due",
        table_name="promocode_activations",
    )
    op.drop_index(
        "uq_promocode_activations_pending_user",
        table_name="promocode_activations",
    )
    op.create_index(
        "uq_promocode_activations_pending_user",
        "promocode_activations",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )

    op.drop_column("promocode_activations", "event_sent_at")
    op.drop_column("promocode_activations", "event_last_error")
    op.drop_column("promocode_activations", "event_next_retry_at")
    op.drop_column("promocode_activations", "event_attempt_count")
    op.drop_column("promocode_activations", "event_status")
    op.drop_column("promocode_activations", "next_retry_at")
    op.drop_column("promocode_activations", "attempt_count")
