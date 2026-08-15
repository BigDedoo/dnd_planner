"""Create Phase 2A accounts and account_identities schema.

Revision ID: 0002_phase_2a_accounts
Revises: 0001_phase_1_domain_schema
Create Date: 2026-08-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_phase_2a_accounts"
down_revision: str | Sequence[str] | None = "0001_phase_1_domain_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=120), nullable=True),
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
            "email IS NULL OR btrim(email) <> ''",
            name="ck_accounts_email_not_blank",
        ),
        sa.CheckConstraint(
            "display_name IS NULL OR btrim(display_name) <> ''",
            name="ck_accounts_display_name_not_blank",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_accounts"),
    )
    op.create_index(
        "uq_accounts_email_normalized",
        "accounts",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )

    op.create_table(
        "account_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_subject", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(provider) <> ''",
            name="ck_account_identities_provider_not_blank",
        ),
        sa.CheckConstraint(
            "btrim(provider_subject) <> ''",
            name="ck_account_identities_provider_subject_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="fk_account_identities_account_id_accounts",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_account_identities"),
        sa.UniqueConstraint(
            "provider",
            "provider_subject",
            name="uq_account_identities_provider_subject",
        ),
    )
    op.create_index(
        "ix_account_identities_account_id",
        "account_identities",
        ["account_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_account_identities_account_id",
        table_name="account_identities",
    )
    op.drop_table("account_identities")
    op.drop_index(
        "uq_accounts_email_normalized",
        table_name="accounts",
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.drop_table("accounts")
