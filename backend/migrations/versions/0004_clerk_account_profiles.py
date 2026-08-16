"""Add Clerk-synchronized account profile fields.

Revision ID: 0004_clerk_account_profiles
Revises: 0003_phase_2b_user_accounts
Create Date: 2026-08-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_clerk_account_profiles"
down_revision: str | Sequence[str] | None = "0003_phase_2b_user_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("username", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "accounts",
        sa.Column("profile_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_accounts_username_not_blank",
        "accounts",
        "username IS NULL OR btrim(username) <> ''",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_accounts_username_not_blank",
        "accounts",
        type_="check",
    )
    op.drop_column("accounts", "profile_synced_at")
    op.drop_column("accounts", "username")
