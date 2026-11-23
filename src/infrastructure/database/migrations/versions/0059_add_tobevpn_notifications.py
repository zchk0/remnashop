"""Persist ToBeVPN announcements, read receipts, and pending Android deliveries."""

import sqlalchemy as sa
from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "device_sessions",
        sa.Column(
            "session_id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False
        ),
    )
    op.add_column("device_sessions", sa.Column("verified_telegram_id", sa.BigInteger()))
    op.add_column("device_sessions", sa.Column("push_token", sa.String(512)))
    op.create_unique_constraint("uq_device_sessions_push_token", "device_sessions", ["push_token"])
    op.add_column("auth_tokens", sa.Column("device_session_id", sa.Uuid()))
    op.add_column("tv_pairing_codes", sa.Column("device_session_id", sa.Uuid()))

    op.create_table(
        "tobevpn_notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("action", sa.String(16)),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_tobevpn_notifications_published_at", "tobevpn_notifications", ["published_at"]
    )
    op.create_index("ix_tobevpn_notifications_expires_at", "tobevpn_notifications", ["expires_at"])
    op.create_table(
        "tobevpn_notification_recipients",
        sa.Column(
            "notification_id",
            sa.Uuid(),
            sa.ForeignKey("tobevpn_notifications.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
    )
    op.create_index(
        "ix_tobevpn_recipient_user_notification",
        "tobevpn_notification_recipients",
        ["user_id", "notification_id"],
    )
    op.create_table(
        "tobevpn_notification_reads",
        sa.Column(
            "notification_id",
            sa.Uuid(),
            sa.ForeignKey("tobevpn_notifications.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("reader", sa.String(40), primary_key=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "tobevpn_push_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "notification_id",
            sa.Uuid(),
            sa.ForeignKey("tobevpn_notifications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("device_id", sa.String(128), nullable=False),
        sa.Column("device_session_id", sa.Uuid(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default="0", nullable=False),
        sa.UniqueConstraint("notification_id", "device_id"),
    )
    op.create_index(
        "ix_tobevpn_push_deliveries_due", "tobevpn_push_deliveries", ["available_at", "id"]
    )


def downgrade() -> None:
    op.drop_table("tobevpn_push_deliveries")
    op.drop_table("tobevpn_notification_reads")
    op.drop_table("tobevpn_notification_recipients")
    op.drop_table("tobevpn_notifications")
    op.drop_column("tv_pairing_codes", "device_session_id")
    op.drop_column("auth_tokens", "device_session_id")
    op.drop_constraint("uq_device_sessions_push_token", "device_sessions", type_="unique")
    op.drop_column("device_sessions", "push_token")
    op.drop_column("device_sessions", "verified_telegram_id")
    op.drop_column("device_sessions", "session_id")
