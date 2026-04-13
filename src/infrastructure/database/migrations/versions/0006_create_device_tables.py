"""Create linked_devices, auth_tokens, and tv_pairing_codes tables.

These tables support the ToBeVPN mobile/TV client integration:
- linked_devices: tracks which physical devices are linked to Telegram users
- auth_tokens: deep-link authentication flow for mobile app
- tv_pairing_codes: QR/code-based pairing for Android TV app
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "linked_devices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("device_id", sa.String(128), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("panel_user_uuid", sa.Text(), nullable=True),
        sa.Column("short_uuid", sa.Text(), nullable=True),
        sa.Column("anon_traffic_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("device_name", sa.String(256), nullable=True),
        sa.Column("device_type", sa.String(32), nullable=True),
        sa.Column("platform", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("UTC", sa.func.now()),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("UTC", sa.func.now()),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_linked_devices_device_id", "linked_devices", ["device_id"], unique=True)
    op.create_index("ix_linked_devices_telegram_id", "linked_devices", ["telegram_id"])

    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("token", sa.String(256), nullable=False),
        sa.Column("device_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("short_uuid", sa.Text(), nullable=True),
        sa.Column("panel_user_uuid", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("UTC", sa.func.now()),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("UTC", sa.func.now()),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auth_tokens_token", "auth_tokens", ["token"], unique=True)
    op.create_index("ix_auth_tokens_device_id", "auth_tokens", ["device_id"])
    op.create_index("ix_auth_tokens_status", "auth_tokens", ["status"])

    op.create_table(
        "tv_pairing_codes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("device_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("UTC", sa.func.now()),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("UTC", sa.func.now()),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tv_pairing_codes_code", "tv_pairing_codes", ["code"], unique=True)
    op.create_index("ix_tv_pairing_codes_device_id", "tv_pairing_codes", ["device_id"])
    op.create_index("ix_tv_pairing_codes_status", "tv_pairing_codes", ["status"])


def downgrade() -> None:
    op.drop_table("tv_pairing_codes")
    op.drop_table("auth_tokens")
    op.drop_table("linked_devices")
