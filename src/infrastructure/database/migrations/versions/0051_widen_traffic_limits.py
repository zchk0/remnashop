"""Store large panel traffic limits without int32 overflow."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0051"
down_revision: Union[str, None] = "0050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("subscriptions", "plans"):
        op.alter_column(
            table,
            "traffic_limit",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )


def downgrade() -> None:
    # PostgreSQL rejects values outside int32 rather than truncating existing limits.
    for table in ("plans", "subscriptions"):
        op.alter_column(
            table,
            "traffic_limit",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
        )
