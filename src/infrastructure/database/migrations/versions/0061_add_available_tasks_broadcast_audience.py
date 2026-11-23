"""Allow Telegram broadcasts to target users with available tasks."""

from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE broadcast_audience ADD VALUE IF NOT EXISTS 'AVAILABLE_TASKS'")


def downgrade() -> None:
    op.execute("ALTER TYPE broadcast_audience RENAME TO broadcast_audience_with_tasks")
    op.execute(
        "CREATE TYPE broadcast_audience AS ENUM "
        "('ALL', 'PLAN', 'SUBSCRIBED', 'UNSUBSCRIBED', 'EXPIRED', 'TRIAL')"
    )
    # PostgreSQL rejects the cast if any broadcasts still use the new audience.
    op.execute(
        "ALTER TABLE broadcasts ALTER COLUMN audience TYPE broadcast_audience "
        "USING audience::text::broadcast_audience"
    )
    op.execute("DROP TYPE broadcast_audience_with_tasks")
