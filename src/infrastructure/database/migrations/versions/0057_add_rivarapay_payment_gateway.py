"""Add Rivara Pay and preserve its external payment intent identifier."""

import sqlalchemy as sa
from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE payment_gateway_type ADD VALUE IF NOT EXISTS 'RIVARAPAY'")
    op.add_column("transactions", sa.Column("provider_payment_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("transactions", "provider_payment_id")
    # PostgreSQL enum values cannot be safely removed while referenced by stored gateways.
