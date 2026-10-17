"""Store Stripe customers and subscription state for PRO memberships."""

import sqlalchemy as sa
from alembic import op

revision = "0015_billing_subscriptions"
down_revision = "0014_account_terms_acceptance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billing_customers",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("stripe_customer_id", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_billing_customers_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_billing_customers"),
        sa.UniqueConstraint(
            "stripe_customer_id",
            name="uq_billing_customers_stripe_customer_id",
        ),
    )
    op.create_table(
        "billing_subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("stripe_price_id", sa.String(255), nullable=True),
        sa.Column("billing_interval", sa.String(16), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "billing_interval IS NULL OR billing_interval IN ('month', 'year')",
            name="ck_billing_subscriptions_billing_interval",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_billing_subscriptions_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_billing_subscriptions"),
        sa.UniqueConstraint(
            "stripe_subscription_id",
            name="uq_billing_subscriptions_stripe_subscription_id",
        ),
    )
    op.create_index(
        "ix_billing_subscriptions_user_id", "billing_subscriptions", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_billing_subscriptions_user_id", "billing_subscriptions")
    op.drop_table("billing_subscriptions")
    op.drop_table("billing_customers")
