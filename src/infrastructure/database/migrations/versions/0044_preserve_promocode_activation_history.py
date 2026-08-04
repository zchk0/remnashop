from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0044"
down_revision: Union[str, None] = "0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "promocodes",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_promocodes_deleted_at",
        "promocodes",
        ["deleted_at"],
        unique=False,
    )

    op.add_column(
        "promocode_activations",
        sa.Column("code_snapshot", sa.String(), nullable=True),
    )
    op.add_column(
        "promocode_activations",
        sa.Column(
            "reward_type_snapshot",
            postgresql.ENUM(name="promocode_reward_type", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "promocode_activations",
        sa.Column("reward_snapshot", sa.Integer(), nullable=True),
    )
    op.add_column(
        "promocode_activations",
        sa.Column("plan_snapshot", postgresql.JSONB(), nullable=True),
    )
    op.execute(
        """
        UPDATE promocode_activations AS activation
        SET code_snapshot = promocode.code,
            reward_type_snapshot = promocode.reward_type,
            reward_snapshot = promocode.reward,
            plan_snapshot = promocode.plan_snapshot
        FROM promocodes AS promocode
        WHERE promocode.id = activation.promocode_id
        """
    )
    op.alter_column("promocode_activations", "code_snapshot", nullable=False)
    op.alter_column("promocode_activations", "reward_type_snapshot", nullable=False)

    op.drop_constraint(
        "promocode_activations_promocode_id_fkey",
        "promocode_activations",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "promocode_activations_promocode_id_fkey",
        "promocode_activations",
        "promocodes",
        ["promocode_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "promocode_activations_promocode_id_fkey",
        "promocode_activations",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "promocode_activations_promocode_id_fkey",
        "promocode_activations",
        "promocodes",
        ["promocode_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_column("promocode_activations", "plan_snapshot")
    op.drop_column("promocode_activations", "reward_snapshot")
    op.drop_column("promocode_activations", "reward_type_snapshot")
    op.drop_column("promocode_activations", "code_snapshot")
    op.drop_index("ix_promocodes_deleted_at", table_name="promocodes")
    op.drop_column("promocodes", "deleted_at")
