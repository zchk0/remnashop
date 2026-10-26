"""Persist Platega subscriptions and a durable callback inbox."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("billing_email", sa.String(255), nullable=True))
    op.create_table(
        "recurring_payments",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("payment_url", sa.Text(), nullable=False),
        sa.Column("plan_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("pricing", postgresql.JSONB(), nullable=False),
        sa.Column("purchase_type", sa.String(16), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("next_charge_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_recurring_payments_user_id", "recurring_payments", ["user_id"])
    op.create_index(
        "uq_recurring_payments_open_user",
        "recurring_payments",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('Pending', 'Active', 'PastDue')"),
    )
    op.create_table(
        "recurring_payment_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("subscription_id", sa.UUID(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("target", postgresql.JSONB()),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_recurring_payment_events_subscription_id",
        "recurring_payment_events",
        ["subscription_id"],
    )
    op.create_index(
        "ix_recurring_payment_events_processed_at", "recurring_payment_events", ["processed_at"]
    )


def downgrade() -> None:
    op.drop_table("recurring_payment_events")
    op.drop_table("recurring_payments")
    op.drop_column("users", "billing_email")
