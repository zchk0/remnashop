from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0043"
down_revision: Union[str, None] = "0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "promocode_activations",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "promocode_activations",
        sa.Column("status", sa.String(length=16), server_default="APPLIED", nullable=False),
    )
    op.add_column(
        "promocode_activations",
        sa.Column(
            "remote_action",
            sa.String(length=32),
            server_default="NONE",
            nullable=False,
        ),
    )
    op.add_column(
        "promocode_activations",
        sa.Column("target_remna_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "promocode_activations",
        sa.Column("reset_traffic", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "promocode_activations",
        sa.Column("last_error", sa.Text(), nullable=True),
    )

    op.create_index(
        "ix_promocode_activations_request_id",
        "promocode_activations",
        ["request_id"],
        unique=True,
        postgresql_where=sa.text("request_id IS NOT NULL"),
    )
    op.create_index(
        "ix_promocode_activations_status",
        "promocode_activations",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_promocode_activations_target_remna_id",
        "promocode_activations",
        ["target_remna_id"],
        unique=False,
    )
    op.create_index(
        "uq_promocode_activations_pending_user",
        "promocode_activations",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )


def downgrade() -> None:
    op.drop_index("uq_promocode_activations_pending_user", table_name="promocode_activations")
    op.drop_index(
        "ix_promocode_activations_target_remna_id",
        table_name="promocode_activations",
    )
    op.drop_index("ix_promocode_activations_status", table_name="promocode_activations")
    op.drop_index("ix_promocode_activations_request_id", table_name="promocode_activations")
    op.drop_column("promocode_activations", "last_error")
    op.drop_column("promocode_activations", "reset_traffic")
    op.drop_column("promocode_activations", "target_remna_id")
    op.drop_column("promocode_activations", "remote_action")
    op.drop_column("promocode_activations", "status")
    op.drop_column("promocode_activations", "request_id")
