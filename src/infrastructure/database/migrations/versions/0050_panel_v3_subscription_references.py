"""Allow v3 users without UUIDs and persist recoverable promocode creation targets."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0050"
down_revision: Union[str, None] = "0049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("subscriptions", "user_remna_id", existing_type=sa.UUID(), nullable=True)
    op.add_column("promocode_activations", sa.Column("target_subscription_id", sa.Integer()))
    op.add_column("promocode_activations", sa.Column("target_short_uuid", sa.String(32)))
    op.create_foreign_key(
        "fk_promocode_activations_target_subscription",
        "promocode_activations",
        "subscriptions",
        ["target_subscription_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_promocode_activations_target_subscription_id",
        "promocode_activations",
        ["target_subscription_id"],
    )


def downgrade() -> None:
    # Returning to v2 requires restoring real UUIDs, never generating substitutes.
    op.alter_column("subscriptions", "user_remna_id", existing_type=sa.UUID(), nullable=False)
    op.drop_index("ix_promocode_activations_target_subscription_id", "promocode_activations")
    op.drop_constraint(
        "fk_promocode_activations_target_subscription", "promocode_activations", type_="foreignkey"
    )
    op.drop_column("promocode_activations", "target_short_uuid")
    op.drop_column("promocode_activations", "target_subscription_id")
