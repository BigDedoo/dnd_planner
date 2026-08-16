"""Add date-only confirmed sessions for groups.

Revision ID: 0005_confirmed_group_sessions
Revises: 0004_clerk_account_profiles
Create Date: 2026-08-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_confirmed_group_sessions"
down_revision: str | Sequence[str] | None = "0004_clerk_account_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "confirmed_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("confirmed_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "confirmed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"],
            ["users.id"],
            name="fk_confirmed_sessions_confirmed_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name="fk_confirmed_sessions_group_id_groups",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_confirmed_sessions"),
        sa.UniqueConstraint("group_id", "day", name="uq_confirmed_sessions_group_id_day"),
    )
    op.create_index("ix_confirmed_sessions_day", "confirmed_sessions", ["day"])


def downgrade() -> None:
    op.drop_index("ix_confirmed_sessions_day", table_name="confirmed_sessions")
    op.drop_table("confirmed_sessions")
