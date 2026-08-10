"""Create the Phase 1 domain schema.

Revision ID: 0001_phase_1_domain_schema
Revises:
Create Date: 2026-08-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_phase_1_domain_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("auth_provider", sa.String(length=50), nullable=True),
        sa.Column("auth_subject", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default=sa.text("'UTC'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(display_name) <> ''",
            name="ck_users_display_name_not_blank",
        ),
        sa.CheckConstraint(
            "(auth_provider IS NULL AND auth_subject IS NULL) OR "
            "(auth_provider IS NOT NULL AND auth_subject IS NOT NULL "
            "AND btrim(auth_provider) <> '' AND btrim(auth_subject) <> '')",
            name="ck_users_auth_identity_pair",
        ),
        sa.CheckConstraint(
            "email IS NULL OR btrim(email) <> ''",
            name="ck_users_email_not_blank",
        ),
        sa.CheckConstraint(
            "btrim(timezone) <> ''",
            name="ck_users_timezone_not_blank",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint(
            "auth_provider",
            "auth_subject",
            name="uq_users_auth_identity",
        ),
    )
    op.create_index(
        "uq_users_email_normalized",
        "users",
        [sa.literal_column("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.create_index("ix_users_display_name", "users", ["display_name"])

    op.create_table(
        "groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default=sa.text("'UTC'"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(name) <> ''",
            name="ck_groups_name_not_blank",
        ),
        sa.CheckConstraint(
            "btrim(timezone) <> ''",
            name="ck_groups_timezone_not_blank",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_groups"),
    )
    op.create_index("ix_groups_name", "groups", ["name"])

    op.create_table(
        "group_memberships",
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'organizer', 'member')",
            name="ck_group_memberships_role",
        ),
        sa.CheckConstraint(
            "display_order >= 0",
            name="ck_group_memberships_display_order",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name="fk_group_memberships_group_id_groups",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_group_memberships_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "group_id",
            "user_id",
            name="pk_group_memberships",
        ),
        sa.UniqueConstraint(
            "group_id",
            "display_order",
            name="uq_group_memberships_display_order",
        ),
    )
    op.create_index(
        "ix_group_memberships_user_id",
        "group_memberships",
        ["user_id"],
    )
    op.create_index(
        "ix_group_memberships_group_role",
        "group_memberships",
        ["group_id", "role"],
    )
    op.create_index(
        "uq_group_memberships_one_owner",
        "group_memberships",
        ["group_id"],
        unique=True,
        postgresql_where=sa.text("role = 'owner'"),
    )

    op.create_table(
        "availability",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('available', 'maybe', 'unavailable')",
            name="ck_availability_status",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_availability_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "day", name="pk_availability"),
    )
    op.create_index(
        "ix_availability_day_user_id",
        "availability",
        ["day", "user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_availability_day_user_id", table_name="availability")
    op.drop_table("availability")

    op.drop_index(
        "uq_group_memberships_one_owner",
        table_name="group_memberships",
    )
    op.drop_index(
        "ix_group_memberships_group_role",
        table_name="group_memberships",
    )
    op.drop_index(
        "ix_group_memberships_user_id",
        table_name="group_memberships",
    )
    op.drop_table("group_memberships")

    op.drop_index("ix_groups_name", table_name="groups")
    op.drop_table("groups")

    op.drop_index("ix_users_display_name", table_name="users")
    op.drop_index(
        "uq_users_email_normalized",
        table_name="users",
    )
    op.drop_table("users")
