"""Add reusable, hashed group invite codes.

Revision ID: 0006_group_invites
Revises: 0005_confirmed_group_sessions
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_group_invites"
down_revision = "0005_confirmed_group_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "group_invites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "use_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.CheckConstraint("use_count >= 0", name="ck_group_invites_use_count"),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name="fk_group_invites_group_id_groups",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_group_invites_created_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_group_invites"),
    )
    op.create_index(
        "ix_group_invites_code_hash",
        "group_invites",
        ["code_hash"],
        unique=True,
    )
    op.create_index(
        "uq_group_invites_one_active",
        "group_invites",
        ["group_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
        sqlite_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_group_invites_one_active", table_name="group_invites")
    op.drop_index("ix_group_invites_code_hash", table_name="group_invites")
    op.drop_table("group_invites")
