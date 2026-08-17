"""Add nullable per-group membership nicknames.

Revision ID: 0007_onboarding_group_nicknames
Revises: 0006_group_invites
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_onboarding_group_nicknames"
down_revision = "0006_group_invites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "group_memberships",
        sa.Column("nickname", sa.String(length=120), nullable=True),
    )
    op.create_check_constraint(
        "ck_group_memberships_nickname_not_blank",
        "group_memberships",
        "nickname IS NULL OR btrim(nickname) <> ''",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_group_memberships_nickname_not_blank",
        "group_memberships",
        type_="check",
    )
    op.drop_column("group_memberships", "nickname")
