"""Keep v2 UUIDs while preparing numeric user IDs for panel v3."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0048"
down_revision: Union[str, None] = "0047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = (
    ("subscriptions", "panel_user_id"),
    ("promocode_activations", "target_panel_user_id"),
    ("linked_devices", "panel_user_id"),
    ("auth_tokens", "panel_user_id"),
)


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.add_column(table, sa.Column(column, sa.BigInteger(), nullable=True))
        op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    for table, column in reversed(_COLUMNS):
        op.drop_index(f"ix_{table}_{column}", table_name=table)
        op.drop_column(table, column)
