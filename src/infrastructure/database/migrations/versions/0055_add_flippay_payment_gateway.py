"""Add the FlipPay gateway type; startup creates its inactive settings entry."""

from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE payment_gateway_type ADD VALUE IF NOT EXISTS 'FLIPPAY'")


def downgrade() -> None:
    # PostgreSQL cannot remove an enum value while retaining historical transactions.
    pass
