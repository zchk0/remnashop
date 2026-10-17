"""Add rewarded channel subscriptions and their durable claim ledger."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column(
            "earning", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
    )
    op.create_table(
        "channel_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_url", sa.String(), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("reset_traffic", sa.Boolean(), nullable=False),
        sa.Column("discount", sa.Integer(), nullable=False),
        sa.Column("max_claims", sa.Integer()),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id", ondelete="RESTRICT")),
        sa.Column("trial_plan_id", sa.Integer(), sa.ForeignKey("plans.id", ondelete="RESTRICT")),
        sa.Column("trial_days", sa.Integer()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("days >= 0 AND discount BETWEEN 0 AND 100", name="valid_task_reward"),
        sa.CheckConstraint("max_claims IS NULL OR max_claims > 0", name="valid_task_capacity"),
        sa.CheckConstraint("trial_days IS NULL OR trial_days > 0", name="valid_task_trial_days"),
    )
    op.create_table(
        "channel_claims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("channel_tasks.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("subscription_applied", sa.Boolean(), nullable=False),
        sa.Column("reset_started", sa.Boolean(), nullable=False),
        sa.Column("reset_applied", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("task_id", "user_id", name="uq_channel_claim_user"),
    )
    op.create_index("ix_channel_claims_user_id", "channel_claims", ["user_id"])


def downgrade() -> None:
    op.drop_table("channel_claims")
    op.drop_table("channel_tasks")
    op.drop_column("settings", "earning")
