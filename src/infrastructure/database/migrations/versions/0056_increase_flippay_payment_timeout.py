"""Increase the previous FlipPay default timeout to sixty minutes."""

from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE payment_gateways
        SET settings = jsonb_set(settings, '{payment_timeout_minutes}', '60'::jsonb)
        WHERE type::text = 'FLIPPAY'
          AND jsonb_typeof(settings) = 'object'
          AND (
              settings->>'payment_timeout_minutes' IS NULL
              OR settings->>'payment_timeout_minutes' = '30'
          )
        """
    )


def downgrade() -> None:
    # Keep the stored timeout: an explicit admin value of sixty is indistinguishable.
    pass
