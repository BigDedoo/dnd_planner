"""Add account_id to users for Phase 2B.

Revision ID: 0003_phase_2b_user_accounts
Revises: 0002_phase_2a_accounts
Create Date: 2026-08-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_phase_2b_user_accounts"
down_revision: str | Sequence[str] | None = "0002_phase_2a_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("account_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_users_account_id_accounts",
        "users",
        "accounts",
        ["account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_users_account_id",
        "users",
        ["account_id"],
        unique=True,
        postgresql_where=sa.text("account_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_users_account_id",
        table_name="users",
        postgresql_where=sa.text("account_id IS NOT NULL"),
    )
    op.drop_constraint(
        "fk_users_account_id_accounts",
        "users",
        type_="foreignkey",
    )
    op.drop_column("users", "account_id")
