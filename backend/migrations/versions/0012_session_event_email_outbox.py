"""Add personal opt-out and an initially empty transactional event-email outbox.

Revision ID: 0012_session_event_email_outbox
Revises: 0011_session_reminder_minutes
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_session_event_email_outbox"
down_revision = "0011_session_reminder_minutes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "important_session_emails_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.create_table(
        "session_event_email_outbox",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("dedupe_key", sa.String(255), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["confirmed_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "kind IN ('session_scheduled', 'session_changed', 'session_cancelled')",
            name="ck_session_event_email_outbox_kind",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_session_event_email_outbox_attempt_count"
        ),
        sa.UniqueConstraint(
            "dedupe_key", name="uq_session_event_email_outbox_dedupe_key"
        ),
    )
    op.create_index(
        "ix_session_event_email_outbox_due",
        "session_event_email_outbox",
        ["next_attempt_at", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_session_event_email_outbox_due", table_name="session_event_email_outbox"
    )
    op.drop_table("session_event_email_outbox")
    op.drop_column("users", "important_session_emails_enabled")
