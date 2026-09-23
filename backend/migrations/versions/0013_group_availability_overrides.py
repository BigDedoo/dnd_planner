"""Add opt-in per-membership availability, without changing global responses.

Revision ID: 0013_group_availability_overrides
Revises: 0012_session_event_email_outbox
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_group_availability_overrides"
down_revision = "0012_session_event_email_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "group_memberships",
        sa.Column(
            "availability_mode", sa.String(16), nullable=False, server_default="global"
        ),
    )
    op.add_column(
        "group_memberships",
        sa.Column(
            "separate_availability_initialized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_check_constraint(
        "ck_group_memberships_availability_mode",
        "group_memberships",
        "availability_mode IN ('global', 'separate')",
    )
    op.create_table(
        "group_availability",
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint(
            "group_id", "user_id", "day", name="pk_group_availability"
        ),
        sa.ForeignKeyConstraint(
            ["group_id", "user_id"],
            ["group_memberships.group_id", "group_memberships.user_id"],
            name="fk_group_availability_membership",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('available', 'maybe', 'unavailable')",
            name="ck_group_availability_status",
        ),
    )
    op.create_index(
        "ix_group_availability_group_day_user",
        "group_availability",
        ["group_id", "day", "user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_group_availability_group_day_user", table_name="group_availability"
    )
    op.drop_table("group_availability")
    op.drop_constraint(
        "ck_group_memberships_availability_mode", "group_memberships", type_="check"
    )
    op.drop_column("group_memberships", "separate_availability_initialized")
    op.drop_column("group_memberships", "availability_mode")
