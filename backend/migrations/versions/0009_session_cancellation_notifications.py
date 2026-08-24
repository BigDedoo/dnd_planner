"""Add session cancellation state and notification delivery deduplication.

Revision ID: 0009_session_notifications
Revises: 0008_scheduled_sessions_rsvps
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_session_notifications"
down_revision = "0008_scheduled_sessions_rsvps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "confirmed_sessions",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "confirmed_sessions",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "confirmed_sessions",
        sa.Column("cancelled_by_user_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_confirmed_sessions_cancelled_by_user_id_users",
        "confirmed_sessions",
        "users",
        ["cancelled_by_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "session_notification_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column(
            "delivered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('session_scheduled', 'session_changed', 'session_cancelled', "
            "'upcoming_session_reminder', 'missing_rsvp_reminder')",
            name="ck_session_notification_deliveries_kind",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["confirmed_sessions.id"],
            name="fk_session_notifications_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"],
            ["users.id"],
            name="fk_session_notifications_recipient_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dedupe_key", name="uq_session_notification_deliveries_dedupe_key"
        ),
    )
    op.create_index(
        "ix_session_notification_deliveries_recipient_user_id",
        "session_notification_deliveries",
        ["recipient_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_session_notification_deliveries_recipient_user_id",
        table_name="session_notification_deliveries",
    )
    op.drop_table("session_notification_deliveries")
    op.drop_constraint(
        "fk_confirmed_sessions_cancelled_by_user_id_users",
        "confirmed_sessions",
        type_="foreignkey",
    )
    op.drop_column("confirmed_sessions", "cancelled_by_user_id")
    op.drop_column("confirmed_sessions", "cancelled_at")
    op.drop_column("confirmed_sessions", "updated_at")
