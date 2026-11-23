"""Allow ToBeVPN announcements to target devices without an account."""

import sqlalchemy as sa
from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tobevpn_notifications",
        sa.Column("guests_only", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_check_constraint(
        "ck_tobevpn_notifications_installation_audience",
        "tobevpn_notifications",
        "NOT (is_public AND guests_only)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_tobevpn_notifications_installation_audience", "tobevpn_notifications", type_="check"
    )
    op.drop_column("tobevpn_notifications", "guests_only")
