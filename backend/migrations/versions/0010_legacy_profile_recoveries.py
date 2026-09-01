"""Add temporary legacy profile recovery records.

Revision ID: 0010_legacy_profile_recoveries
Revises: 0009_session_notifications
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_legacy_profile_recoveries"
down_revision = "0009_session_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "legacy_profile_recoveries",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by_account_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "(claimed_at IS NULL AND claimed_by_account_id IS NULL) OR "
            "(claimed_at IS NOT NULL AND claimed_by_account_id IS NOT NULL)",
            name="ck_legacy_profile_recoveries_claim_state",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_legacy_profile_recoveries_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["claimed_by_account_id"],
            ["accounts.id"],
            name="fk_legacy_profile_recoveries_claimed_by_account_id_accounts",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_legacy_profile_recoveries"),
    )
    op.create_index(
        "ix_legacy_profile_recoveries_claimed_at",
        "legacy_profile_recoveries",
        ["claimed_at"],
    )
    op.create_index(
        "ix_legacy_profile_recoveries_claimed_by_account_id",
        "legacy_profile_recoveries",
        ["claimed_by_account_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_legacy_profile_recoveries_claimed_by_account_id",
        table_name="legacy_profile_recoveries",
    )
    op.drop_index(
        "ix_legacy_profile_recoveries_claimed_at",
        table_name="legacy_profile_recoveries",
    )
    op.drop_table("legacy_profile_recoveries")
