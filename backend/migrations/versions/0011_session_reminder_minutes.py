"""Add one global personal session reminder preference.

Revision ID: 0011_session_reminder_minutes
Revises: 0010_legacy_profile_recoveries
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_session_reminder_minutes"
down_revision = "0010_legacy_profile_recoveries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "session_reminder_minutes",
            sa.Integer(),
            nullable=True,
            server_default=sa.text("1440"),
        ),
    )
    op.create_check_constraint(
        "ck_users_session_reminder_minutes",
        "users",
        "session_reminder_minutes IS NULL OR session_reminder_minutes IN (60, 180, 720, 1440, 4320, 10080)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_session_reminder_minutes", "users", type_="check")
    op.drop_column("users", "session_reminder_minutes")
