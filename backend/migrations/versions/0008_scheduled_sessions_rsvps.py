"""Add scheduled-session details and member RSVPs.

Revision ID: 0008_scheduled_sessions_rsvps
Revises: 0007_onboarding_group_nicknames
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_scheduled_sessions_rsvps"
down_revision = "0007_onboarding_group_nicknames"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable fields deliberately retain date-only sessions created before Sessions v2.
    op.add_column(
        "confirmed_sessions", sa.Column("title", sa.String(length=120), nullable=True)
    )
    op.add_column(
        "confirmed_sessions", sa.Column("start_time", sa.Time(), nullable=True)
    )
    op.add_column(
        "confirmed_sessions", sa.Column("duration_minutes", sa.Integer(), nullable=True)
    )
    op.add_column("confirmed_sessions", sa.Column("notes", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_confirmed_sessions_duration_minutes",
        "confirmed_sessions",
        "duration_minutes IS NULL OR duration_minutes BETWEEN 15 AND 1440",
    )
    op.create_check_constraint(
        "ck_confirmed_sessions_title_not_blank",
        "confirmed_sessions",
        "title IS NULL OR btrim(title) <> ''",
    )

    op.create_table(
        "confirmed_session_rsvps",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "responded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('going', 'maybe', 'declined')",
            name="ck_confirmed_session_rsvps_status",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["confirmed_sessions.id"],
            name="fk_confirmed_session_rsvps_session_id_confirmed_sessions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_confirmed_session_rsvps_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("session_id", "user_id"),
    )
    op.create_index(
        "ix_confirmed_session_rsvps_user_id",
        "confirmed_session_rsvps",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_confirmed_session_rsvps_user_id", table_name="confirmed_session_rsvps"
    )
    op.drop_table("confirmed_session_rsvps")
    op.drop_constraint(
        "ck_confirmed_sessions_title_not_blank", "confirmed_sessions", type_="check"
    )
    op.drop_constraint(
        "ck_confirmed_sessions_duration_minutes", "confirmed_sessions", type_="check"
    )
    op.drop_column("confirmed_sessions", "notes")
    op.drop_column("confirmed_sessions", "duration_minutes")
    op.drop_column("confirmed_sessions", "start_time")
    op.drop_column("confirmed_sessions", "title")
