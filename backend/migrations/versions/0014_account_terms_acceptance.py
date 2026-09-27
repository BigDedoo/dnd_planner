"""Record explicit account Terms acceptance without accepting for existing users."""

import sqlalchemy as sa
from alembic import op

revision = "0014_account_terms_acceptance"
down_revision = "0013_group_availability_override"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("terms_version", sa.String(64), nullable=True))
    op.add_column(
        "accounts",
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_accounts_terms_acceptance_pair",
        "accounts",
        "(terms_version IS NULL AND terms_accepted_at IS NULL) OR "
        "(terms_version IS NOT NULL AND btrim(terms_version) <> '' "
        "AND terms_accepted_at IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_accounts_terms_acceptance_pair", "accounts", type_="check")
    op.drop_column("accounts", "terms_accepted_at")
    op.drop_column("accounts", "terms_version")
